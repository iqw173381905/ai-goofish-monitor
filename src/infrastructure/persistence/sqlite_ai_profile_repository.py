"""
AI 模型档案（中转站配置）SQLite 仓储。
保存多个 OpenAI 兼容中转站的 base_url / api_key / model_name / proxy_url，
供 Web UI 下拉选择并一键应用到当前生效配置。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.infrastructure.persistence.sqlite_connection import sqlite_connection


def _now_str() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "base_url": row["base_url"],
        "api_key": row["api_key"],
        "model_name": row["model_name"],
        "proxy_url": row["proxy_url"] or "",
        "enabled": bool(row["enabled"]) if "enabled" in row.keys() else True,
        "priority": int(row["priority"]) if "priority" in row.keys() else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_ai_profiles(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with sqlite_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM ai_profiles ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_ai_profile(
    profile_id: int, db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    with sqlite_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM ai_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)


def create_ai_profile(
    *,
    name: str,
    base_url: str,
    api_key: str,
    model_name: str,
    proxy_url: Optional[str] = None,
    enabled: bool = True,
    priority: int = 0,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    now = _now_str()
    with sqlite_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO ai_profiles(name, base_url, api_key, model_name, proxy_url, enabled, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                base_url.strip().rstrip("/"),
                api_key.strip(),
                model_name.strip(),
                (proxy_url or "").strip() or None,
                1 if enabled else 0,
                int(priority),
                now,
                now,
            ),
        )
        conn.commit()
        return get_ai_profile(cursor.lastrowid, db_path=db_path) or {}


def update_ai_profile(
    profile_id: int,
    *,
    name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    proxy_url: Optional[str] = None,
    enabled: Optional[bool] = None,
    priority: Optional[int] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    existing = get_ai_profile(profile_id, db_path=db_path)
    if existing is None:
        return None
    new_name = (name if name is not None else existing["name"]).strip()
    new_base_url = (
        (base_url if base_url is not None else existing["base_url"]).strip().rstrip("/")
    )
    new_api_key = (api_key if api_key is not None else existing["api_key"]).strip()
    new_model = (model_name if model_name is not None else existing["model_name"]).strip()
    if proxy_url is None:
        new_proxy = existing.get("proxy_url") or None
    else:
        new_proxy = proxy_url.strip() or None
    new_enabled = existing.get("enabled", True) if enabled is None else enabled
    new_priority = existing.get("priority", 0) if priority is None else priority
    with sqlite_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE ai_profiles
            SET name = ?, base_url = ?, api_key = ?, model_name = ?, proxy_url = ?,
                enabled = ?, priority = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_name, new_base_url, new_api_key, new_model, new_proxy,
                1 if new_enabled else 0, int(new_priority), _now_str(), profile_id,
            ),
        )
        conn.commit()
    return get_ai_profile(profile_id, db_path=db_path)


def get_failover_profiles(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """返回参与故障转移的档案：enabled=1，按 priority DESC、id ASC 排序。"""
    with sqlite_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM ai_profiles WHERE enabled = 1 ORDER BY priority DESC, id ASC"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def set_ai_profile_failover_order(ids: List[int], db_path: Optional[str] = None) -> None:
    """按给定 id 顺序重设 priority：越靠前 priority 越大。"""
    now = _now_str()
    with sqlite_connection(db_path) as conn:
        total = len(ids)
        for rank, profile_id in enumerate(ids):
            conn.execute(
                "UPDATE ai_profiles SET priority = ?, updated_at = ? WHERE id = ?",
                (total - rank, now, int(profile_id)),
            )
        conn.commit()


def delete_ai_profile(profile_id: int, db_path: Optional[str] = None) -> bool:
    with sqlite_connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM ai_profiles WHERE id = ?", (profile_id,))
        conn.commit()
        return cursor.rowcount > 0
