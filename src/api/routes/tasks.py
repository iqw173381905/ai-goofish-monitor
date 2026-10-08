"""
任务管理路由
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from typing import List
import os
import threading
import asyncio
import aiofiles
import time
from datetime import datetime
from src.api.dependencies import (
    get_process_service,
    get_scheduler_service,
    get_task_generation_service,
    get_task_service,
)
from src.services.task_service import TaskService
from src.services.process_service import ProcessService
from src.services.scheduler_service import SchedulerService
from src.services.task_generation_service import TaskGenerationService
from src.services.task_generation_runner import (
    build_task_create,
    run_ai_generation_job,
)
from src.services.task_payloads import serialize_task, serialize_tasks
from src.domain.models.task import TaskCreate, TaskUpdate, TaskGenerateRequest
from src.prompt_utils import generate_criteria
from src.utils import resolve_task_log_path
from src.services.account_strategy_service import normalize_account_strategy
from src.infrastructure.persistence.storage_names import build_result_filename
from src.services.price_history_service import delete_price_snapshots
from src.services.result_storage_service import delete_result_file_records
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
router = APIRouter(prefix="/api/tasks", tags=["tasks"])

async def _reload_scheduler_if_needed(
    task_service: TaskService,
    scheduler_service: SchedulerService,
):
    tasks = await task_service.get_all_tasks()
    await scheduler_service.reload_jobs(tasks)


def _has_keyword_rules(rules) -> bool:
    return bool(rules and len(rules) > 0)


def _set_generating_flag(task_id: int, value: bool) -> None:
    """置位/清位 criteria_generating，带重试兜底（Windows 上偶发 sqlite 写锁）。
    置位时记录 criteria_generating_since（生成开始时间），用于识别 worker 卡死
    产生的 stale 标记（AI 中转无响应时，start_task 据此放行启动）。"""
    since_value = datetime.now().isoformat(timespec="seconds") if value else None
    for attempt in range(3):
        try:
            with sqlite_connection() as conn:
                conn.execute(
                    "UPDATE tasks SET criteria_generating = ?, criteria_generating_since = ? WHERE id = ?",
                    (1 if value else 0, since_value, task_id),
                )
                conn.commit()
            return
        except Exception as e:
            if attempt == 2:
                print(f"[后台] 更新 criteria 状态失败 task={task_id}: {e}")
                return
            time.sleep(0.5)


def _regenerate_criteria_in_background(task_id: int, keyword: str, description: str) -> None:
    """后台重新生成 AI 分析标准：写 prompts 文件并更新 DB 的 ai_prompt_criteria_file。

    切换/更新 AI 模式时不再同步等待 AI 生成（SiliconFlow 生成标准较慢，
    曾导致 PATCH 保存长时间无响应），改为保存秒回、后台异步生成。
    生成期间置 criteria_generating=1，前端据此禁用启动并展示生成中状态。
    """
    from datetime import datetime

    safe_keyword = "".join(
        c for c in keyword.lower().replace(' ', '_') if c.isalnum() or c in "_-"
    ).rstrip()
    output_filename = f"prompts/{safe_keyword}_criteria.txt"

    def _set_generating(value: bool) -> None:
        _set_generating_flag(task_id, value)

    def worker():
        _set_generating(True)
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # 120 秒超时兜底：AI 中转站无响应/排队过久时主动失败，
                # 避免 generating 状态无限期挂起（前端"生成中"永不结束）。
                generated = loop.run_until_complete(
                    asyncio.wait_for(
                        generate_criteria(
                            user_description=description,
                            reference_file_path="prompts/macbook_criteria.txt",
                        ),
                        timeout=120,
                    )
                )
            finally:
                loop.close()
        except Exception as e:
            print(f"[后台] 生成 AI 分析标准失败 task={task_id}: {e}")
            _set_generating(False)
            return
        if not generated or not generated.strip():
            print(f"[后台] AI 返回的分析标准为空 task={task_id}，跳过写入")
            _set_generating(False)
            return
        try:
            os.makedirs("prompts", exist_ok=True)
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write(generated)
            # 写 DB（标准文件 + 清生成标记 + 记录生成时间），带重试兜底
            written = False
            for attempt in range(3):
                try:
                    with sqlite_connection() as conn:
                        conn.execute(
                            "UPDATE tasks SET ai_prompt_criteria_file = ?, criteria_generating = 0, criteria_generating_since = NULL, criteria_generated_at = ? WHERE id = ?",
                            (
                                output_filename,
                                datetime.now().isoformat(timespec="seconds"),
                                task_id,
                            ),
                        )
                        conn.commit()
                    written = True
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"[后台] 保存 AI 分析标准失败 task={task_id}: {e}")
                    time.sleep(0.5)
            if not written:
                _set_generating(False)
                return
            print(f"[后台] AI 分析标准已生成并保存: {output_filename}")
        except Exception as e:
            print(f"[后台] 保存 AI 分析标准失败 task={task_id}: {e}")
            _set_generating(False)

    threading.Thread(target=worker, daemon=True).start()


def _validate_final_account_strategy(existing_task, task_update: TaskUpdate) -> None:
    account_state_file = (
        task_update.account_state_file
        if task_update.account_state_file is not None
        else existing_task.account_state_file
    )
    account_strategy = normalize_account_strategy(
        task_update.account_strategy,
        account_state_file,
    )
    task_update.account_strategy = account_strategy
    if account_strategy == "fixed" and not account_state_file:
        raise HTTPException(status_code=400, detail="固定账号模式下必须选择账号。")
@router.get("", response_model=List[dict])
async def get_tasks(
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """获取所有任务"""
    tasks = await service.get_all_tasks()
    return serialize_tasks(tasks, scheduler_service)
@router.get("/{task_id}", response_model=dict)
async def get_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """获取单个任务"""
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    return serialize_task(task, scheduler_service)
@router.post("/", response_model=dict)
async def create_task(
    task_create: TaskCreate,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """创建新任务"""
    task = await service.create_task(task_create)
    await _reload_scheduler_if_needed(service, scheduler_service)
    return {"message": "任务创建成功", "task": serialize_task(task, scheduler_service)}
@router.post("/generate", response_model=dict)
async def generate_task(
    req: TaskGenerateRequest,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    generation_service: TaskGenerationService = Depends(get_task_generation_service),
):
    """创建任务。AI模式会生成分析标准，关键词模式直接保存规则。"""
    print(f"收到任务生成请求: {req.task_name}，模式: {req.decision_mode}")

    try:
        mode = req.decision_mode or "ai"
        if mode == "ai":
            # 先创建占位任务（分析标准为空、生成中标记=1），页面立即可见"生成中"，
            # 后台 job 再异步生成分析标准并回填；不再等生成完才让任务出现在列表。
            task = await service.create_task(build_task_create(req, ""))
            _set_generating_flag(task.id, True)
            # 置位后重新读取任务，确保返回给前端的 generating 状态为 true（页面立即显示"生成中"）
            refreshed = await service.get_task(task.id)
            task_for_response = refreshed if refreshed is not None else task
            job = await generation_service.create_job(req.task_name)
            generation_service.track(
                run_ai_generation_job(
                    job_id=job.job_id,
                    task_id=task.id,
                    req=req,
                    task_service=service,
                    scheduler_service=scheduler_service,
                    generation_service=generation_service,
                )
            )
            return JSONResponse(
                status_code=200,
                content={
                    "message": "任务已创建，AI 分析标准正在后台生成。",
                    "task": serialize_task(task_for_response, scheduler_service),
                    "job": job.model_dump(mode="json"),
                },
            )

        task = await service.create_task(build_task_create(req, ""))
        await _reload_scheduler_if_needed(service, scheduler_service)
        return {"message": "任务创建成功。", "task": serialize_task(task, scheduler_service)}

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"AI任务生成API发生未知错误: {str(e)}"
        print(error_msg)
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)
@router.get("/generate-jobs/{job_id}", response_model=dict)
async def get_task_generation_job(
    job_id: str,
    generation_service: TaskGenerationService = Depends(get_task_generation_service),
):
    """获取任务生成作业状态"""
    job = await generation_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务生成作业未找到")
    return {"job": job.model_dump(mode="json")}
@router.patch("/{task_id}", response_model=dict)
async def update_task(
    task_id: int,
    task_update: TaskUpdate,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """更新任务"""
    try:
        existing_task = await service.get_task(task_id)
        if not existing_task:
            raise HTTPException(status_code=404, detail="任务未找到")
        _validate_final_account_strategy(existing_task, task_update)

        current_mode = getattr(existing_task, "decision_mode", "ai") or "ai"
        target_mode = task_update.decision_mode or current_mode
        description_changed = (
            task_update.description is not None
            and task_update.description != existing_task.description
        )
        switched_to_ai = current_mode != "ai" and target_mode == "ai"

        if target_mode == "keyword":
            final_rules = (
                task_update.keyword_rules
                if task_update.keyword_rules is not None
                else getattr(existing_task, "keyword_rules", [])
            )
            final_required = (
                task_update.required_keywords
                if task_update.required_keywords is not None
                else getattr(existing_task, "required_keywords", [])
            )
            final_optional = (
                task_update.optional_keywords
                if task_update.optional_keywords is not None
                else getattr(existing_task, "optional_keywords", [])
            )
            if not (
                _has_keyword_rules(final_rules)
                or bool(final_required)
                or bool(final_optional)
            ):
                raise HTTPException(status_code=400, detail="关键词模式下至少需要一个关键词。")
        if target_mode == "ai" and (
            description_changed or switched_to_ai or task_update.regenerate_criteria is True
        ):
            description_for_ai = (
                task_update.description
                if task_update.description is not None
                else existing_task.description
            )
            if not str(description_for_ai or "").strip():
                raise HTTPException(status_code=400, detail="AI 模式下详细需求不能为空。")
            # 保存秒回：AI 分析标准改在后台异步生成（见 _regenerate_criteria_in_background）
            _regenerate_criteria_in_background(
                task_id=task_id,
                keyword=existing_task.keyword,
                description=description_for_ai,
            )
        task = await service.update_task(task_id, task_update)
        await _reload_scheduler_if_needed(service, scheduler_service)
        return {"message": "任务更新成功", "task": serialize_task(task, scheduler_service)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{task_id}/criteria-content", response_model=dict)
async def get_task_criteria_content(
    task_id: int,
    service: TaskService = Depends(get_task_service),
):
    """返回任务当前 AI 分析标准文件内容（供前端"查看标准"弹窗展示）。"""
    try:
        task = await service.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务未找到")
        filename = getattr(task, "ai_prompt_criteria_file", "") or ""
        content = ""
        updated_at = getattr(task, "criteria_generated_at", None)
        if filename:
            path = filename if os.path.isabs(filename) else os.path.join(os.getcwd(), filename)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
        return {
            "filename": filename,
            "content": content,
            "updated_at": updated_at,
            "size": len(content),
        }
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"读取 AI 分析标准内容失败: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@router.delete("/{task_id}", response_model=dict)
async def delete_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    process_service: ProcessService = Depends(get_process_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """删除任务"""
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")

    await process_service.stop_task(task_id)
    success = await service.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务未找到")
    await _reload_scheduler_if_needed(service, scheduler_service)
    try:
        keyword = (task.keyword or "").strip()
        if keyword:
            remaining_tasks = await service.get_all_tasks()
            keyword_still_in_use = any(
                (remaining_task.keyword or "").strip() == keyword
                for remaining_task in remaining_tasks
            )
            if not keyword_still_in_use:
                await delete_result_file_records(build_result_filename(keyword))
                delete_price_snapshots(keyword)
    except Exception as e:
        print(f"删除任务结果文件时出错: {e}")

    try:
        log_file_path = resolve_task_log_path(task_id, task.task_name)
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
    except Exception as e:
        print(f"删除任务日志文件时出错: {e}")
    return {"message": "任务删除成功"}
@router.post("/start/{task_id}", response_model=dict)
async def start_task(
    task_id: int,
    task_service: TaskService = Depends(get_task_service),
    process_service: ProcessService = Depends(get_process_service),
):
    """启动单个任务"""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    if not task.enabled:
        raise HTTPException(status_code=400, detail="任务已被禁用，无法启动")
    if task.is_running:
        raise HTTPException(status_code=400, detail="任务已在运行中")
    if (task.decision_mode or "ai") == "ai" and getattr(
        task, "criteria_generating", False
    ):
        # stale 检测：生成标记超过 10 分钟未完成视为 worker 卡死（AI 中转无响应）。
        # 此时清除标记并放行启动，避免"生成中"永远阻塞启动按钮。
        since_text = getattr(task, "criteria_generating_since", None)
        stale = True
        if since_text:
            try:
                since_dt = datetime.fromisoformat(since_text)
                stale = (datetime.now() - since_dt).total_seconds() > 600
            except (ValueError, TypeError):
                stale = True
        if stale:
            try:
                with sqlite_connection() as conn:
                    conn.execute(
                        "UPDATE tasks SET criteria_generating = 0, criteria_generating_since = NULL WHERE id = ?",
                        (task_id,),
                    )
                    conn.commit()
            except Exception as e:
                print(f"清除卡死的生成标记失败 task={task_id}: {e}")
        else:
            raise HTTPException(
                status_code=400,
                detail="AI 分析标准正在生成中，请等待生成完成后再启动任务。",
            )
    success = await process_service.start_task(task_id, task.task_name)
    if not success:
        raise HTTPException(status_code=500, detail="启动任务失败")
    return {"message": f"任务 '{task.task_name}' 已启动"}
@router.post("/stop/{task_id}", response_model=dict)
async def stop_task(
    task_id: int,
    task_service: TaskService = Depends(get_task_service),
    process_service: ProcessService = Depends(get_process_service),
):
    """停止单个任务"""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    await process_service.stop_task(task_id)
    return {"message": f"任务ID {task_id} 已发送停止信号"}
