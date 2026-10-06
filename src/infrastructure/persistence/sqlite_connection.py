"""
SQLite 连接与 schema 初始化。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.infrastructure.persistence.storage_names import DEFAULT_DATABASE_PATH


BUSY_TIMEOUT_MS = 5000

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS app_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY,
        task_name TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        keyword TEXT NOT NULL,
        description TEXT,
        analyze_images INTEGER NOT NULL,
        max_pages INTEGER NOT NULL,
        personal_only INTEGER NOT NULL,
        min_price TEXT,
        max_price TEXT,
        cron TEXT,
        ai_prompt_base_file TEXT NOT NULL,
        ai_prompt_criteria_file TEXT NOT NULL,
        account_state_file TEXT,
        account_strategy TEXT NOT NULL,
        free_shipping INTEGER NOT NULL,
        new_publish_option TEXT,
        region TEXT,
        decision_mode TEXT NOT NULL,
        keyword_rules_json TEXT NOT NULL,
        required_keywords_json TEXT NOT NULL DEFAULT '[]',
        optional_keywords_json TEXT NOT NULL DEFAULT '[]',
        optional_min_hits INTEGER,
        is_running INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS result_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        result_filename TEXT NOT NULL,
        keyword TEXT NOT NULL,
        task_name TEXT NOT NULL,
        crawl_time TEXT NOT NULL,
        publish_time TEXT,
        price REAL,
        price_display TEXT,
        item_id TEXT,
        title TEXT,
        link TEXT,
        link_unique_key TEXT NOT NULL,
        seller_nickname TEXT,
        is_recommended INTEGER NOT NULL,
        analysis_source TEXT,
        keyword_hit_count INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        raw_json TEXT NOT NULL,
        UNIQUE(result_filename, link_unique_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS price_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword_slug TEXT NOT NULL,
        keyword TEXT NOT NULL,
        task_name TEXT NOT NULL,
        snapshot_time TEXT NOT NULL,
        snapshot_day TEXT NOT NULL,
        run_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        title TEXT,
        price REAL NOT NULL,
        price_display TEXT,
        tags_json TEXT NOT NULL,
        region TEXT,
        seller TEXT,
        publish_time TEXT,
        link TEXT,
        UNIQUE(keyword_slug, run_id, item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS result_blacklist_rules (
        result_filename TEXT PRIMARY KEY,
        blacklist_keywords_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        base_url TEXT NOT NULL,
        api_key TEXT NOT NULL,
        model_name TEXT NOT NULL,
        proxy_url TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tasks_name ON tasks(task_name)",
    """
    CREATE INDEX IF NOT EXISTS idx_results_filename_crawl
    ON result_items(result_filename, crawl_time DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_results_filename_publish
    ON result_items(result_filename, publish_time DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_results_filename_price
    ON result_items(result_filename, price DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_results_filename_recommended
    ON result_items(result_filename, is_recommended, analysis_source, crawl_time DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_snapshots_keyword_time
    ON price_snapshots(keyword_slug, snapshot_time DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_snapshots_keyword_item_time
    ON price_snapshots(keyword_slug, item_id, snapshot_time DESC)
    """,
)


def get_database_path() -> str:
    return os.getenv("APP_DATABASE_FILE", DEFAULT_DATABASE_PATH)


def _prepare_database_file(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")


def init_schema(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    _migrate_result_items_status(conn)
    _migrate_task_keyword_columns(conn)
    _migrate_task_criteria_status(conn)
    _migrate_task_criteria_since(conn)
    conn.commit()


def _migrate_result_items_status(conn: sqlite3.Connection) -> None:
    """为 result_items 表添加 status 列（仅执行一次）。"""
    row = conn.execute(
        "SELECT value FROM app_metadata WHERE key = 'migration:result_items_status'"
    ).fetchone()
    if row is not None:
        return
    cols = [r[1] for r in conn.execute("PRAGMA table_info(result_items)").fetchall()]
    if "status" not in cols:
        conn.execute(
            "ALTER TABLE result_items ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
        )
    conn.execute(
        "INSERT OR REPLACE INTO app_metadata(key, value) VALUES ('migration:result_items_status', 'done')"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_results_filename_status_crawl"
        " ON result_items(result_filename, status, crawl_time DESC)"
    )


def _migrate_task_keyword_columns(conn: sqlite3.Connection) -> None:
    """为 tasks 表添加双组关键词列（仅执行一次，兼容旧库）。"""
    row = conn.execute(
        "SELECT value FROM app_metadata WHERE key = 'migration:task_keyword_columns'"
    ).fetchone()
    if row is not None:
        return
    cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    if "required_keywords_json" not in cols:
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN required_keywords_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "optional_keywords_json" not in cols:
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN optional_keywords_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "optional_min_hits" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN optional_min_hits INTEGER")
    conn.execute(
        "INSERT OR REPLACE INTO app_metadata(key, value) VALUES ('migration:task_keyword_columns', 'done')"
    )


def _migrate_task_criteria_status(conn: sqlite3.Connection) -> None:
    """为 tasks 表添加 AI 标准生成状态列（仅执行一次，兼容旧库）。"""
    row = conn.execute(
        "SELECT value FROM app_metadata WHERE key = 'migration:task_criteria_status'"
    ).fetchone()
    if row is not None:
        return
    cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    if "criteria_generating" not in cols:
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN criteria_generating INTEGER NOT NULL DEFAULT 0"
        )
    if "criteria_generated_at" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN criteria_generated_at TEXT")
    conn.execute(
        "INSERT OR REPLACE INTO app_metadata(key, value) VALUES ('migration:task_criteria_status', 'done')"
    )


def _migrate_task_criteria_since(conn: sqlite3.Connection) -> None:
    """为 tasks 表添加 criteria_generating_since 列：记录生成中状态的开始时间，
    用于识别 worker 卡死（AI 中转无响应）导致的 stale 生成标记，
    start_task 据此判断放行。"""
    row = conn.execute(
        "SELECT value FROM app_metadata WHERE key = 'migration:task_criteria_since'"
    ).fetchone()
    if row is not None:
        return
    cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    if "criteria_generating_since" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN criteria_generating_since TEXT")
    conn.execute(
        "INSERT OR REPLACE INTO app_metadata(key, value) VALUES ('migration:task_criteria_since', 'done')"
    )


@contextmanager
def sqlite_connection(
    db_path: str | None = None,
) -> Iterator[sqlite3.Connection]:
    path = db_path or get_database_path()
    _prepare_database_file(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _apply_pragmas(conn)
        yield conn
    finally:
        conn.close()
