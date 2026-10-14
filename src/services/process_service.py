"""
进程管理服务
负责管理爬虫进程的启动和停止
"""

import asyncio
import contextlib
import os
import signal
import sys
from datetime import datetime
from typing import Awaitable, Callable, Dict, TextIO

from src.ai_handler import send_ntfy_notification
from src.config import STATE_FILE
from src.failure_guard import FailureGuard
from src.infrastructure.persistence.sqlite_task_repository import find_task_by_name_sync
from src.utils import build_task_log_path

STOP_TIMEOUT_SECONDS = 20
SPIDER_DEBUG_LIMIT_ENV = "SPIDER_DEBUG_LIMIT"
LifecycleHook = Callable[[int], Awaitable[None] | None]


class TaskBusyError(Exception):
    """已有其他任务的爬虫进程在运行时抛出。

    服务器只有 2GB 内存，单个 Chromium 就要占数百 MB，多浏览器并发极易
    耗尽内存导致整机无响应，因此同一时间只允许一个任务运行。
    """


class ProcessService:
    """进程管理服务"""

    def __init__(self):
        self.processes: Dict[int, asyncio.subprocess.Process] = {}
        self.log_paths: Dict[int, str] = {}
        self.log_handles: Dict[int, TextIO] = {}
        self.task_names: Dict[int, str] = {}
        self.exit_watchers: Dict[int, asyncio.Task] = {}
        self.failure_guard = FailureGuard()
        self._on_started: LifecycleHook | None = None
        self._on_stopped: LifecycleHook | None = None
        # 启动互斥锁：防止调度器同时触发多个任务时，两个 start_task 交错执行
        # 都通过"无运行中任务"检查、最终并发起两个浏览器（2026-10-14 实测发生过）。
        self._start_lock = asyncio.Lock()

    def set_lifecycle_hooks(
        self,
        *,
        on_started: LifecycleHook | None = None,
        on_stopped: LifecycleHook | None = None,
    ) -> None:
        self._on_started = on_started
        self._on_stopped = on_stopped

    async def _invoke_hook(self, hook: LifecycleHook | None, task_id: int) -> None:
        if hook is None:
            return
        result = hook(task_id)
        if asyncio.iscoroutine(result):
            await result

    def _resolve_cookie_path(self, task_name: str) -> str | None:
        """Best-effort cookie/state path for a task.

        必须与 scraper 运行时实际选用的登录态文件一致（见
        resolve_effective_state_path），否则 FailureGuard 记录失败时用的是
        真实路径（如 state/acc_1.json），而启动检查时却用另一个路径，
        导致「登录态已更新自动恢复」永远检测不到，任务被暂停后无法自愈。
        """
        try:
            from src.scraper import resolve_effective_state_path

            task = find_task_by_name_sync(task_name)
            task_config = {
                "account_state_file": task.account_state_file if task else None
            }
            state_path = resolve_effective_state_path(task_config)
            if state_path and os.path.exists(state_path):
                return state_path
        except Exception:
            pass

        return STATE_FILE if os.path.exists(STATE_FILE) else None

    def is_running(self, task_id: int) -> bool:
        """检查任务是否正在运行"""
        process = self.processes.get(task_id)
        return process is not None and process.returncode is None

    async def _ensure_login_fresh(self, task_name: str) -> bool:
        """任务启动前确保闲鱼登录态有效。

        流程：
        1. 检测 token 是否临期/过期（check_state_file_login_valid）
        2. 有效 → 直接返回 True
        3. 临期 → 自动跑 refresh_login.py --auto-only --headless 续期
        4. 续期成功 → 返回 True；失败 → 通知用户手动更新，返回 False
        """
        from src.scraper import check_state_file_login_valid, resolve_effective_state_path
        from src.infrastructure.persistence.sqlite_task_repository import find_task_by_name_sync

        # 解析任务的登录态文件
        try:
            task = find_task_by_name_sync(task_name)
            task_config = {"account_state_file": task.account_state_file if task else None}
            state_path = resolve_effective_state_path(task_config)
        except Exception:
            state_path = STATE_FILE if os.path.exists(STATE_FILE) else None

        if not state_path:
            print(f"[登录续期] 任务 '{task_name}' 未找到登录态文件，跳过续期检查")
            return True

        # 检测 token 有效性（600秒缓冲：临期也触发续期）
        try:
            valid, msg = check_state_file_login_valid(state_path, buffer_seconds=600)
        except Exception as e:
            print(f"[登录续期] 检测登录态失败: {e}")
            return True  # 检测失败不阻塞任务启动

        if valid:
            return True

        print(f"[登录续期] 任务 '{task_name}' 登录态临期/过期: {msg}")
        print(f"[登录续期] 自动触发 token 续期...")

        # 自动续期：只做 token 轮换，不弹扫码（会话彻底失效时退出码 2）
        script = os.path.join(os.getcwd(), "refresh_login.py")
        if not os.path.exists(script):
            print(f"[登录续期] 续期脚本不存在: {script}")
            await self._notify_login_expired(task_name, msg)
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, script, "--auto-only", "--headless",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
            except asyncio.TimeoutError:
                proc.kill()
                print(f"[登录续期] 续期超时（180秒），终止")
                await self._notify_login_expired(task_name, "自动续期超时")
                return False

            output = stdout.decode("utf-8", errors="ignore") if stdout else ""
            # 输出最后几行到日志
            for line in output.strip().split("\n")[-5:]:
                if line.strip():
                    print(f"[登录续期] {line.strip()}")

            if proc.returncode == 0:
                print(f"[登录续期] 任务 '{task_name}' token 续期成功")
                return True
            elif proc.returncode == 2:
                print(f"[登录续期] 会话已彻底失效，需要人工扫码登录")
            else:
                print(f"[登录续期] 续期失败（退出码 {proc.returncode}）")
            await self._notify_login_expired(task_name, msg)
            return False
        except Exception as e:
            print(f"[登录续期] 执行续期脚本异常: {e}")
            await self._notify_login_expired(task_name, msg)
            return False

    async def _notify_login_expired(self, task_name: str, reason: str) -> None:
        """登录失效通知用户手动更新"""
        print(f"[登录续期] 任务 '{task_name}' 无法自动续期，请到『设置 → 账号管理』手动重新登录")
        try:
            await send_ntfy_notification(
                {
                    "商品标题": f"[登录失效] {task_name}",
                    "当前售价": "N/A",
                    "商品链接": "#",
                },
                f"闲鱼登录态已失效，自动续期失败。\n原因: {reason}\n"
                f"请到『设置 → 账号管理』页面重新扫码登录后，再手动启动任务。\n",
            )
        except Exception as e:
            print(f"[登录续期] 发送通知失败: {e}")

    async def _drain_finished_process(self, task_id: int) -> None:
        process = self.processes.get(task_id)
        if process is None or process.returncode is None:
            return

        watcher = self.exit_watchers.get(task_id)
        if watcher is not None:
            await asyncio.shield(watcher)
            return

        self._cleanup_runtime(task_id, process)
        await self._invoke_hook(self._on_stopped, task_id)

    def _open_log_file(self, task_id: int, task_name: str) -> tuple[str, TextIO]:
        os.makedirs("logs", exist_ok=True)
        log_file_path = build_task_log_path(task_id, task_name)
        log_file_handle = open(log_file_path, "a", encoding="utf-8")
        return log_file_path, log_file_handle

    def _build_spawn_command(self, task_name: str) -> list[str]:
        command = [
            sys.executable,
            "-u",
            "spider_v2.py",
            "--task-name",
            task_name,
        ]
        debug_limit = str(os.getenv(SPIDER_DEBUG_LIMIT_ENV, "")).strip()
        if debug_limit.isdigit() and int(debug_limit) > 0:
            command.extend(["--debug-limit", debug_limit])
        return command

    async def _spawn_process(
        self,
        task_name: str,
        log_file_handle: TextIO,
    ) -> asyncio.subprocess.Process:
        preexec_fn = os.setsid if sys.platform != "win32" else None
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUTF8"] = "1"
        return await asyncio.create_subprocess_exec(
            *self._build_spawn_command(task_name),
            stdout=log_file_handle,
            stderr=log_file_handle,
            preexec_fn=preexec_fn,
            env=child_env,
        )

    def _register_runtime(
        self,
        task_id: int,
        task_name: str,
        process: asyncio.subprocess.Process,
        log_file_path: str,
        log_file_handle: TextIO,
    ) -> None:
        self.processes[task_id] = process
        self.log_paths[task_id] = log_file_path
        self.log_handles[task_id] = log_file_handle
        self.task_names[task_id] = task_name
        self.exit_watchers[task_id] = asyncio.create_task(self._watch_process_exit(process))

    def _running_task_names(self, exclude: int | None = None) -> list[str]:
        """返回当前仍在运行的任务名（已结束但未清理的不算）。"""
        names = []
        for tid, process in self.processes.items():
            if exclude is not None and tid == exclude:
                continue
            if process is not None and process.returncode is None:
                names.append(self.task_names.get(tid, f"ID:{tid}"))
        return names

    async def start_task(self, task_id: int, task_name: str) -> bool:
        """启动任务进程"""
        async with self._start_lock:
            return await self._start_task_locked(task_id, task_name)

    async def _start_task_locked(self, task_id: int, task_name: str) -> bool:
        await self._drain_finished_process(task_id)
        if self.is_running(task_id):
            print(f"任务 '{task_name}' (ID: {task_id}) 已在运行中")
            return False

        # 2GB 内存单并发限制：已有其他任务在跑时拒绝启动，避免多 Chromium
        # 并发耗尽内存导致整机无响应（2026-10-14 故障）。
        for tid in list(self.processes.keys()):
            if tid != task_id:
                await self._drain_finished_process(tid)
        busy = self._running_task_names(exclude=task_id)
        if busy:
            print(f"任务 '{task_name}' 跳过启动：已有任务 {busy} 正在运行（单并发内存保护）")
            raise TaskBusyError(f"任务「{busy[0]}」正在运行中，请等待其完成后再启动")

        decision = self.failure_guard.should_skip_start(
            task_name,
            cookie_path=self._resolve_cookie_path(task_name),
        )
        if decision.skip:
            await self._notify_skip(task_name, decision)
            return False

        # 任务启动前检测登录态 token 是否临期，临期则自动续期
        if not await self._ensure_login_fresh(task_name):
            return False

        log_file_path = ""
        log_file_handle = None
        try:
            log_file_path, log_file_handle = self._open_log_file(task_id, task_name)
            process = await self._spawn_process(task_name, log_file_handle)
        except Exception as exc:
            self._close_log_handle(log_file_handle)
            print(f"启动任务 '{task_name}' 失败: {exc}")
            return False

        self._register_runtime(task_id, task_name, process, log_file_path, log_file_handle)
        print(f"启动任务 '{task_name}' (PID: {process.pid})")
        await self._invoke_hook(self._on_started, task_id)
        return True

    async def _notify_skip(self, task_name: str, decision) -> None:
        print(
            f"[FailureGuard] 跳过启动任务 '{task_name}'，已暂停重试 "
            f"(连续失败 {decision.consecutive_failures}/{self.failure_guard.threshold})"
        )
        if not decision.should_notify:
            return
        try:
            await send_ntfy_notification(
                {
                    "商品标题": f"[任务暂停] {task_name}",
                    "当前售价": "N/A",
                    "商品链接": "#",
                },
                "任务处于暂停状态，将跳过执行。\n"
                f"原因: {decision.reason}\n"
                f"连续失败: {decision.consecutive_failures}/{self.failure_guard.threshold}\n"
                f"暂停到: {decision.paused_until.strftime('%Y-%m-%d %H:%M:%S') if decision.paused_until else 'N/A'}\n"
                "修复方法: 更新登录态/cookies文件后会自动恢复。",
            )
        except Exception as exc:
            print(f"发送任务暂停通知失败: {exc}")

    async def _watch_process_exit(self, process: asyncio.subprocess.Process) -> None:
        await process.wait()
        task_id = self._find_task_id_by_process(process)
        if task_id is None:
            return
        self._cleanup_runtime(task_id, process)
        await self._invoke_hook(self._on_stopped, task_id)

    def _find_task_id_by_process(self, process: asyncio.subprocess.Process) -> int | None:
        for task_id, current_process in self.processes.items():
            if current_process is process:
                return task_id
        return None

    def _cleanup_runtime(
        self,
        task_id: int,
        process: asyncio.subprocess.Process,
    ) -> None:
        if self.processes.get(task_id) is not process:
            return
        self.processes.pop(task_id, None)
        self.log_paths.pop(task_id, None)
        self.task_names.pop(task_id, None)
        self._close_log_handle(self.log_handles.pop(task_id, None))
        self.exit_watchers.pop(task_id, None)

    def _close_log_handle(self, log_handle: TextIO | None) -> None:
        if log_handle is None:
            return
        with contextlib.suppress(Exception):
            log_handle.close()

    def _append_stop_marker(self, log_path: str | None) -> None:
        if not log_path:
            return
        try:
            timestamp = datetime.now().strftime(" %Y-%m-%d %H:%M:%S")
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(f"[{timestamp}] !!! 任务已被终止 !!!\n")
        except Exception as exc:
            print(f"写入任务终止标记失败: {exc}")

    async def stop_task(self, task_id: int) -> bool:
        """停止任务进程"""
        await self._drain_finished_process(task_id)
        process = self.processes.get(task_id)
        if process is None:
            print(f"任务 ID {task_id} 没有正在运行的进程")
            return False
        if process.returncode is not None:
            await self._await_exit_watcher(task_id)
            print(f"任务进程 {process.pid} (ID: {task_id}) 已退出，略过停止")
            return False

        try:
            await self._terminate_process(process, task_id)
            self._append_stop_marker(self.log_paths.get(task_id))
            await self._await_exit_watcher(task_id)
            print(f"任务进程 {process.pid} (ID: {task_id}) 已终止")
            return True
        except ProcessLookupError:
            print(f"进程 (ID: {task_id}) 已不存在")
            return False
        except Exception as exc:
            print(f"停止任务进程 (ID: {task_id}) 时出错: {exc}")
            return False

    async def _terminate_process(
        self,
        process: asyncio.subprocess.Process,
        task_id: int,
    ) -> None:
        if sys.platform != "win32":
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:
            process.terminate()

        try:
            await asyncio.wait_for(process.wait(), timeout=STOP_TIMEOUT_SECONDS)
            return
        except asyncio.TimeoutError:
            print(
                f"任务进程 {process.pid} (ID: {task_id}) 未在 "
                f"{STOP_TIMEOUT_SECONDS} 秒内退出，准备强制终止..."
            )

        if sys.platform != "win32":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
        await process.wait()

    async def _await_exit_watcher(self, task_id: int) -> None:
        watcher = self.exit_watchers.get(task_id)
        if watcher is None:
            return
        await asyncio.shield(watcher)

    def reindex_after_delete(self, deleted_task_id: int) -> None:
        """删除任务后同步重排运行时索引，避免任务下标漂移。"""
        self.processes = self._reindex_mapping(self.processes, deleted_task_id)
        self.log_paths = self._reindex_mapping(self.log_paths, deleted_task_id)
        self.log_handles = self._reindex_mapping(self.log_handles, deleted_task_id)
        self.task_names = self._reindex_mapping(self.task_names, deleted_task_id)
        self.exit_watchers = self._reindex_mapping(self.exit_watchers, deleted_task_id)

    def _reindex_mapping(self, mapping: Dict[int, object], deleted_task_id: int) -> Dict[int, object]:
        reindexed: Dict[int, object] = {}
        for task_id, value in mapping.items():
            if task_id == deleted_task_id:
                continue
            next_task_id = task_id - 1 if task_id > deleted_task_id else task_id
            reindexed[next_task_id] = value
        return reindexed

    async def stop_all(self) -> None:
        """停止所有任务进程"""
        task_ids = list(self.processes.keys())
        for task_id in task_ids:
            await self.stop_task(task_id)
