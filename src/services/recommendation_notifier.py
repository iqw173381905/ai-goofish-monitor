"""
推荐商品后端推送：任务完成后直接推 ntfy，不依赖前端轮询。
"""
import json
import os
from datetime import datetime
from typing import Dict, List

from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.infrastructure.persistence.storage_names import build_result_filename
from src.services.notification_service import build_notification_service


_STATE_FILE = "data/recommendation_notify_state.json"


def _load_state() -> Dict[str, str]:
    """加载每个任务上次推送时间 {task_id: iso_time}"""
    try:
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_state(state: Dict[str, str]) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:
        print(f"[推荐推送] 保存状态失败: {e}")



async def notify_new_recommendations(task_id: int) -> int:
    """
    任务完成后调用：查询本次新增的推荐商品，通过 ntfy 推送。
    返回推送的商品数量。
    """
    # 查任务信息
    try:
        with sqlite_connection() as conn:
            row = conn.execute(
                "SELECT task_name, keyword FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if not row:
            return 0
        task_name, keyword = row[0], (row[1] or "").strip()
        if not keyword:
            return 0
    except Exception as e:
        print(f"[推荐推送] 查询任务失败 task={task_id}: {e}")
        return 0

    # 上次推送时间
    state = _load_state()
    last_time = state.get(str(task_id), "2000-01-01T00:00:00")

    # 查新增推荐
    filename = build_result_filename(keyword)
    items: List[Dict] = []
    try:
        with sqlite_connection() as conn:
            rows = conn.execute(
                "SELECT link_unique_key, title, price, raw_json, crawl_time FROM result_items "
                "WHERE result_filename = ? AND is_recommended = 1 AND crawl_time > ? "
                "ORDER BY crawl_time ASC",
                (filename, last_time),
            ).fetchall()
            for r in rows:
                # result_items 没有 reason 列，推荐理由在 raw_json 的 ai_analysis 里
                reason = ""
                try:
                    raw = json.loads(r[3] or "{}")
                    reason = (raw.get("ai_analysis") or {}).get("reason") or ""
                except Exception:
                    reason = ""
                items.append({
                    "id": r[0],
                    "title": r[1] or "",
                    "price": r[2] or "",
                    "reason": reason,
                    "crawl_time": r[4] or "",
                })
    except Exception as e:
        print(f"[推荐推送] 查询推荐商品失败 task={task_id}: {e}")
        return 0

    if not items:
        return 0

    # 推送
    try:
        service = build_notification_service()
    except Exception as e:
        print(f"[推荐推送] 构建通知服务失败: {e}")
        return 0

    sent = 0
    max_time = last_time
    for item in items:
        try:
            product_data = {
                "title": item["title"],
                "price": item["price"],
                "link": item["id"],  # link_unique_key 通常是商品链接或ID
                "task_name": task_name,
            }
            await service.send_notification(product_data, item["reason"])
            sent += 1
            if item["crawl_time"] > max_time:
                max_time = item["crawl_time"]
        except Exception as e:
            print(f"[推荐推送] 推送失败 {item['title'][:20]}: {e}")

    # 更新上次推送时间（即使部分失败，也推进到已成功的最大值，避免重复）
    if sent > 0:
        state[str(task_id)] = max_time
        _save_state(state)
        print(f"[推荐推送] 任务 '{task_name}' 推送了 {sent} 个推荐商品")

    return sent
