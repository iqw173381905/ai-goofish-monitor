"""
共享浏览器服务（Phase 2：多任务并发内存优化）

背景：2GB 内存服务器上，每个爬虫任务独立拉起一个 Chromium（数百 MB），
两个并发就可能耗尽内存导致整机无响应（2026-10-14 故障）。

本服务在应用进程内常驻 1 个 Chromium（--remote-debugging-port 的 CDP 模式，
因容器内 Playwright 版本已移除 launch_server），各任务子进程通过
connect_over_cdp 连接，只创建自己独立的 browser context（登录态隔离、
互不串号；proxy 按任务落在各自 context 上）。任务结束只关闭自己的
context，绝不关闭共享浏览器。

懒启动：应用启动时不占内存，首次任务需要时才拉起浏览器；浏览器进程死了
下次 ensure_running 自动重拉，不影响应用主进程。
"""

import asyncio
import json
import shutil
import tempfile
import urllib.request

SHARED_BROWSER_CDP_ENV = "GOOFISH_SHARED_BROWSER_CDP"
_PROFILE_PREFIX = "goofish-shared-browser-"


class SharedBrowserService:
    """应用内单例的共享 Chromium（CDP 模式）。"""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._cdp_url: str | None = None
        self._profile_dir: str | None = None
        self._lock = asyncio.Lock()

    @property
    def cdp_url(self) -> str | None:
        return self._cdp_url

    def _is_alive(self) -> bool:
        return (
            self._proc is not None
            and self._cdp_url is not None
            and self._proc.returncode is None
        )

    async def ensure_running(self) -> str:
        """确保共享浏览器在运行，返回 CDP endpoint（http://127.0.0.1:PORT）。

        已在运行则直接返回；进程已死则自动重拉。调用方（ProcessService）
        在启动任务子进程前调用，把 endpoint 经环境变量传给子进程。
        """
        async with self._lock:
            if self._is_alive():
                return self._cdp_url
            await self._teardown()
            await self._launch()
            return self._cdp_url

    async def _launch(self) -> None:
        # 延迟导入：避免模块顶层循环依赖，且复用现有的减肥参数与 headless 逻辑。
        from playwright.async_api import async_playwright

        from src.config import RUN_HEADLESS
        from src.scraper import prepare_chromium_launch_args

        port = _find_free_port()
        async with async_playwright() as p:
            exe = p.chromium.executable_path

        # 每次启动用全新的临时 profile 目录：避免复用目录时的
        # SingletonLock 冲突（旧进程残留锁会导致新进程直接退出）。
        # 共享浏览器只是各任务 context 的容器，任务登录态走各自的
        # storage_state，不依赖 profile 持久化。
        profile_dir = tempfile.mkdtemp(prefix=_PROFILE_PREFIX)
        self._profile_dir = profile_dir

        args = list(prepare_chromium_launch_args())
        if RUN_HEADLESS:
            # 与 refresh_login.py 一致：强制完整版 Chromium 的新 headless 模式
            args.append("--headless=new")
        cmd = [
            exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            *args,
        ]
        # NOTE: --no-sandbox / --disable-dev-shm-usage 等已在共享参数里。
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._cdp_url = f"http://127.0.0.1:{port}"
        await self._wait_debugger_ready(self._cdp_url, self._proc)
        print(f"[共享浏览器] 已启动: {self._cdp_url} (pid={self._proc.pid})")

    @staticmethod
    async def _wait_debugger_ready(cdp_url: str, proc, timeout: float = 25.0) -> None:
        """等待 DevTools HTTP 端点就绪，超时则杀掉进程并抛异常。"""
        import time

        deadline = time.time() + timeout
        last_err: Exception | None = None
        while time.time() < deadline:
            if proc.returncode is not None:
                raise RuntimeError(
                    f"共享浏览器进程启动后立即退出 (code={proc.returncode})"
                )
            try:
                req = urllib.request.Request(
                    cdp_url + "/json/version", method="GET"
                )
                with urllib.request.urlopen(req, timeout=2) as resp:
                    info = json.loads(resp.read().decode("utf-8", "replace"))
                    if info.get("webSocketDebuggerUrl"):
                        return
            except Exception as exc:  # noqa: BLE001 - 就绪轮询，任何异常都重试
                last_err = exc
            await asyncio.sleep(0.5)
        try:
            proc.terminate()
        except Exception:
            pass
        raise RuntimeError(f"共享浏览器 DevTools 端点 {timeout}s 未就绪: {last_err}")

    async def _teardown(self) -> None:
        if self._proc is not None:
            proc, self._proc = self._proc, None
            if proc.returncode is None:
                try:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        proc.kill()
                except Exception:
                    pass
        self._cdp_url = None
        if self._profile_dir:
            profile_dir, self._profile_dir = self._profile_dir, None
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception:
                pass

    async def close(self) -> None:
        """应用关闭时释放共享浏览器。"""
        async with self._lock:
            await self._teardown()
            print("[共享浏览器] 已关闭")


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
