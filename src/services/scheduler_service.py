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

        # 每天凌晨 3 点：为所有 AI 模式任务重新生成分析标准
        try:
            self.scheduler.add_job(
                self._regenerate_all_criteria,
                trigger=build_cron_trigger("0 3 * * *", timezone=self.scheduler.timezone),
                id="daily_criteria_regen",
                name="Daily: regenerate AI criteria",
                replace_existing=True,
            )
            print("  -> 已添加每日 AI 标准重生成任务 (0 3 * * *)")
        except ValueError as e:
            print(f"  -> [警告] 每日标准重生成任务添加失败: {e}")

        print("定时任务加载完成")

    async def _run_task(self, task_id: int, task_name: str):
        """执行定时任务"""
        print(f"定时任务触发: 正在为任务 '{task_name}' 启动爬虫...")
        # 并发不再受限：多任务通过共享浏览器架构共用 1 个 Chromium 进程
        await self.process_service.start_task(task_id, task_name)


    async def _regenerate_all_criteria(self):
        """每天为所有启用的 AI 模式任务重新生成分析标准。"""
        print("[定时] 开始每日 AI 分析标准重生成...")
        try:
            from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
            tasks = await SqliteTaskRepository().find_all()
        except Exception as e:
            print(f"[定时] 读取任务列表失败: {e}")
            return
        count = 0
        for task in tasks:
            try:
                if not getattr(task, "enabled", False):
                    continue
                if (getattr(task, "decision_mode", "ai") or "ai") != "ai":
                    continue
                description = (getattr(task, "description", "") or "").strip()
                keyword = (getattr(task, "keyword", "") or "").strip()
                if not description or not keyword:
                    continue
                # 跳过正在生成中的，避免重复触发
                if getattr(task, "criteria_generating", False):
                    print(f"[定时] 任务 '{task.task_name}' 正在生成中，跳过")
                    continue
                from src.api.routes.tasks import _regenerate_criteria_in_background
                _regenerate_criteria_in_background(task.id, keyword, description)
                count += 1
                print(f"[定时] 已触发任务 '{task.task_name}' 的标准重生成")
            except Exception as e:
                print(f"[定时] 任务 '{getattr(task, 'task_name', '?')}' 重生成触发失败: {e}")
        print(f"[定时] 每日 AI 标准重生成触发完成，共 {count} 个任务")