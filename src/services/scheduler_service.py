"""
调度服务
负责管理定时任务的调度
"""
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from typing import List

from src.core.cron_utils import build_cron_trigger
from src.domain.models.task import Task
from src.services.process_service import ProcessService
from src.infrastructure.persistence.sqlite_connection import sqlite_connection


class SchedulerService:
    """调度服务"""

    def __init__(self, process_service: ProcessService):
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self.process_service = process_service

    def start(self):
        """启动调度器"""
        if not self.scheduler.running:
            self.scheduler.start()
            print("调度器已启动")

    def stop(self):
        """停止调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            print("调度器已停止")

    def get_next_run_time(self, task_id: int):
        job = self.scheduler.get_job(f"task_{task_id}")
        if job is None:
            return None

        next_run_time = getattr(job, "next_run_time", None)
        if next_run_time is not None:
            return next_run_time

        trigger = getattr(job, "trigger", None)
        if trigger is None or not hasattr(trigger, "get_next_fire_time"):
            return None

        try:
            now = datetime.now(self.scheduler.timezone)
            return trigger.get_next_fire_time(None, now)
        except Exception:
            return None

    async def reload_jobs(self, tasks: List[Task]):
        """重新加载所有定时任务"""
        print("正在重新加载定时任务...")
        self.scheduler.remove_all_jobs()

        for task in tasks:
            if task.enabled and task.cron:
                try:
                    trigger = build_cron_trigger(
                        task.cron,
                        timezone=self.scheduler.timezone,
                    )
                    self.scheduler.add_job(
                        self._run_task,
                        trigger=trigger,
                        args=[task.id, task.task_name],
                        id=f"task_{task.id}",
                        name=f"Scheduled: {task.task_name}",
                        replace_existing=True
                    )
                    print(f"  -> 已为任务 '{task.task_name}' 添加定时规则: '{task.cron}'")
                except ValueError as e:
                    print(f"  -> [警告] 任务 '{task.task_name}' 的 Cron 表达式无效: {e}")

        print("定时任务加载完成")

    async def _run_task(self, task_id: int, task_name: str):
        """执行定时任务"""
        # AI 标准生成中时跳过本次定时触发，避免用旧标准跑任务。
        # stale 判定与手动启动保持一致：超过 10 分钟视为 worker 卡死，放行。
        try:
            with sqlite_connection() as conn:
                row = conn.execute(
                    "SELECT criteria_generating, criteria_generating_since, decision_mode FROM tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
            if row:
                generating = bool(row[0])
                if generating and (row[2] or "ai") == "ai":
                    stale = True
                    if row[1]:
                        try:
                            since_dt = datetime.fromisoformat(row[1])
                            stale = (datetime.now() - since_dt).total_seconds() > 600
                        except (ValueError, TypeError):
                            stale = True
                    if not stale:
                        print(f"定时任务跳过: 任务 '{task_name}' 的 AI 标准正在生成中，本轮不启动")
                        return
                    # stale：清标记后放行（与手动启动一致）
                    try:
                        with sqlite_connection() as conn:
                            conn.execute(
                                "UPDATE tasks SET criteria_generating = 0, criteria_generating_since = NULL WHERE id = ?",
                                (task_id,),
                            )
                            conn.commit()
                    except Exception as e:
                        print(f"清除卡死的生成标记失败 task={task_id}: {e}")
        except Exception as e:
            print(f"检查生成状态失败 task={task_id}，继续执行: {e}")
        print(f"定时任务触发: 正在为任务 '{task_name}' 启动爬虫...")
        # 并发不再受限：多任务通过共享浏览器架构共用 1 个 Chromium 进程
        await self.process_service.start_task(task_id, task_name)
