"""
AI 模型故障转移：主模型持续失败时，自动轮询启用的备用模型档案。

模型（没有"主配置"这种特殊概念，只有档案）：
- 故障转移链 = 启用的档案按 priority 排序（用户自由调整顺序，没有"主配置"概念）。
- "当前生效"仅是标记：档案的 base_url + model_name 与当前生效配置（.env）一致的那条。
- 链只包含已保存的档案；没有任何档案时链为空，调用方应明确提示"没有添加 AI 模型"。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI

# 与 src/config.py 主客户端保持一致的传输层超时兜底（SDK 默认 600s 太长，
# 曾导致单个商品 AI 分析卡满 10 分钟）。SDK 自带重试关闭，避免超时叠加。
PROFILE_CLIENT_TIMEOUT = 120.0

# 客户端缓存：每个商品分析都重建客户端会造成连接/文件描述符抖动，
# 按 (档案 id, updated_at) 缓存，档案更新后自动失效重建。
_client_cache: Dict[tuple, AsyncOpenAI] = {}
_CLIENT_CACHE_MAX = 32


def _norm_base_url(url: Any) -> str:
    return (url or "").strip().rstrip("/")


def _norm_model_name(name: Any) -> str:
    return (name or "").strip()


def _resolve_proxy_url(profile: Dict[str, Any]) -> Optional[str]:
    """档案自带 proxy 优先，否则回退当前环境 PROXY_URL。"""
    proxy = (profile.get("proxy_url") or "").strip()
    if proxy:
        return proxy
    return os.getenv("PROXY_URL") or None


def create_profile_client(profile: Dict[str, Any]) -> AsyncOpenAI:
    """为单个模型档案创建独立的 AsyncOpenAI 客户端。"""
    proxy_url = _resolve_proxy_url(profile)
    http_client = None
    if proxy_url:
        http_client = httpx.AsyncClient(proxy=proxy_url, trust_env=True)
    kwargs: Dict[str, Any] = {
        "api_key": profile.get("api_key") or "",
        "base_url": _norm_base_url(profile.get("base_url")),
        "timeout": PROFILE_CLIENT_TIMEOUT,
        "max_retries": 0,
    }
    if http_client is not None:
        kwargs["http_client"] = http_client
    return AsyncOpenAI(**kwargs)


def _close_client_quietly(client: Any) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _cache_key_for(item: Dict[str, Any]) -> tuple:
    # 链只包含已保存的档案；档案更新后缓存自动失效
    return ("profile", item.get("id"), item.get("updated_at"))


def get_cached_client(item: Dict[str, Any]) -> AsyncOpenAI:
    """获取（或创建并缓存）条目对应的客户端。档案更新后缓存自动失效。"""
    key = _cache_key_for(item)
    client = _client_cache.get(key)
    if client is None:
        prefix = key[:2]
        for old_key in [k for k in _client_cache if k[:2] == prefix and k != key]:
            _close_client_quietly(_client_cache.pop(old_key))
        client = create_profile_client(item)
        if len(_client_cache) >= _CLIENT_CACHE_MAX:
            oldest = next(iter(_client_cache))
            _close_client_quietly(_client_cache.pop(oldest))
        _client_cache[key] = client
    return client


def find_active_profile(
    profiles: List[Dict[str, Any]], env_base_url: str, env_model_name: str
) -> Optional[Dict[str, Any]]:
    """找到与当前生效配置一致的档案；没有则返回 None。"""
    want_url = _norm_base_url(env_base_url)
    want_model = _norm_model_name(env_model_name)
    if not want_url or not want_model:
        return None
    for p in profiles or []:
        if _norm_base_url(p.get("base_url")) == want_url and _norm_model_name(
            p.get("model_name")
        ) == want_model:
            return p
    return None


def _profile_item(profile: Dict[str, Any], *, is_active: bool) -> Dict[str, Any]:
    return {
        "kind": "profile",
        "id": profile.get("id"),
        "name": profile.get("name") or f"档案{profile.get('id')}",
        "base_url": _norm_base_url(profile.get("base_url")),
        "api_key": profile.get("api_key") or "",
        "model_name": _norm_model_name(profile.get("model_name")),
        "proxy_url": (profile.get("proxy_url") or "").strip(),
        "enabled": True,
        "priority": int(profile.get("priority") or 0),
        "updated_at": profile.get("updated_at"),
        "is_active": is_active,
    }


def resolve_failover_chain(
    *,
    env_base_url: str = "",
    env_model_name: str = "",
    env_api_key: str = "",
    env_proxy: str = "",
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """解析故障转移链的实际执行顺序（可序列化条目）。

    启用的档案按 priority 排序（用户通过上移/下移自由调整）；
    与当前生效配置一致的档案仅打 is_active 标记，不改变顺序。
    链只包含已保存的档案；没有任何档案时返回空列表。
    """
    from src.infrastructure.persistence.sqlite_ai_profile_repository import (
        get_failover_profiles,
    )

    profiles = get_failover_profiles(db_path=db_path)
    active = find_active_profile(profiles, env_base_url, env_model_name)
    active_id = active.get("id") if active else None
    return [
        _profile_item(p, is_active=(p.get("id") == active_id))
        for p in profiles
    ]


def clients_for_chain(items: List[Dict[str, Any]]) -> List[Tuple[str, Any, str]]:
    """把链条目转成 (显示名, 客户端, 模型名) 三元组，供 ai_handler 调用。"""
    chain: List[Tuple[str, Any, str]] = []
    for it in items:
        label = f"{it['name']}（{it['model_name']}）"
        chain.append((label, get_cached_client(it), it["model_name"]))
    return chain
