"""
共享浏览器服务（Phase 2：多任务并发内存优化）

背景：2GB 内存服务器上，每个爬虫任务独立拉起一个 Chromium（数百 MB），
两个并发就可能耗尽内存导致整机无响应（2026-10-14 故障）。

本服务在应用进程内常驻 1 个 Chromium（playwright launch_server），各任务
子进程通过 ws_endpoint 连接，只创建自己独立的 browser context（登录态
隔离、互不串号；proxy 按任务落在各自 context 上）。任务结束只关闭自己的
context，绝不关闭共享浏览器。

懒启动：应用启动时不占内存，首次任务需要时才拉起浏览器；浏览器进程死了
下次 ensure_running 自动重拉，不影响应用主进程。
"""

import asyncio

SHARED_BROWSER_WS_ENV = "GOOFISH_SHARED_BROWSER_WS"


class SharedBrowserService:
    """应用内单例的共享 Chromium。"""

    def __init__(self) -> None:
        self._pw = None
        self._server = None
        self._ws_endpoint: str | None = None
        self._lock = asyncio.Lock()

    @property
    def ws_endpoint(self) -> str | None:
        return self._ws_endpoint

    def _is_alive(self) -> bool:
        if not self._server or not self._ws_endpoint:
            return False
        proc = getattr(self._server, "process", None)
        return proc is not None and proc.returncode is None

    async def ensure_running(self) -> str:
        """确保共享浏览器在运行，返回 ws_endpoint。

        已在运行则直接返回；进程已死则自动重拉。调用方（ProcessService）
        在启动任务子进程前调用，把 endpoint 经环境变量传给子进程。
        """
        async with self._lock:
            if self._is_alive():
                return self._ws_endpoint
            await self._teardown()
            await self._launch()
            return self._ws_endpoint

    async def _launch(self) -> None:
        # 延迟导入 scraper：避免模块顶层循环依赖（scraper 侧不导入本模块，
        # 但保持单向依赖更稳妥）。
        from src.config import RUN_HEADLESS
        from src.scraper import prepare_chromium_launch_args, _resolve_browser_channel

        if self._pw is None:
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().start()

        kwargs = {
            "headless": RUN_HEADLESS,
            "args": prepare_chromium_launch_args(),
        }
        channel = _resolve_browser_channel()
        if channel:
            kwargs["channel"] = channel
        # 注意：proxy 按任务轮换，不能落在共享浏览器上；
        # 各任务在自己的 context 上设置 proxy（见 scraper 连接模式）。
        self._server = await self._pw.chromium.launch_server(**kwargs)
        self._ws_endpoint = self._server.ws_endpoint
        print(f"[共享浏览器] 已启动: {self._ws_endpoint}")

    async def _teardown(self) -> None:
        if self._server is not None:
            try:
                await self._server.close()
            except Exception:
                pass
            self._server = None
        self._ws_endpoint = None

    async def close(self) -> None:
        """应用关闭时释放共享浏览器。"""
        async with self._lock:
            await self._teardown()
            if self._pw is not None:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
                self._pw = None
            print("[共享浏览器] 已关闭")
