"""
AI 模型故障转移：当主模型调用持续失败时，自动轮询启用的备用模型档案。

设计：
- 主配置（当前 .env 生效的 OPENAI_*）永远是链上第一顺位。
- 随后按 priority DESC、id ASC 轮询所有 enabled=1 的模型档案，
  与主配置 base_url+model_name 完全相同的档案会被去重跳过。
- 每个模型使用独立的 AsyncOpenAI 客户端，互不干扰。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import AsyncOpenAI

# 与 src/config.py 主客户端保持一致的传输层超时兜底（SDK 默认 600s 太长，
# 曾导致单个商品 AI 分析卡满 10 分钟）。SDK 自带重试关闭，避免超时叠加。
PROFILE_CLIENT_TIMEOUT = 120.0


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
        "base_url": (profile.get("base_url") or "").rstrip("/"),
        "timeout": PROFILE_CLIENT_TIMEOUT,
        "max_retries": 0,
    }
    if http_client is not None:
        kwargs["http_client"] = http_client
    return AsyncOpenAI(**kwargs)


def _same_endpoint(base_url_a: str, model_a: str, base_url_b: str, model_b: str) -> bool:
    return (base_url_a or "").rstrip("/") == (base_url_b or "").rstrip("/") and (
        model_a or ""
    ).strip() == (model_b or "").strip()


def build_model_chain(
    *,
    primary_label: str,
    primary_client: Any,
    primary_base_url: str,
    primary_model_name: str,
    profiles: List[Dict[str, Any]],
) -> List[Tuple[str, Any, str]]:
    """构建故障转移链：[(显示名, 客户端, 模型名), ...]。

    primary_client 可为 None（主配置缺失时），此时链只含启用的档案；
    profiles 应已按 priority 排序（见 get_failover_profiles）。
    """
    chain: List[Tuple[str, Any, str]] = []
    if primary_client is not None:
        chain.append((primary_label, primary_client, primary_model_name))
    for profile in profiles:
        if not profile.get("model_name") or not profile.get("base_url"):
            continue
        if _same_endpoint(
            primary_base_url,
            primary_model_name,
            profile.get("base_url") or "",
            profile.get("model_name") or "",
        ):
            # 与主配置完全相同的档案跳过，避免重复打同一个模型
            continue
        label = f"{profile.get('name') or '档案'}（{profile.get('model_name')}）"
        chain.append((label, create_profile_client(profile), profile["model_name"]))
    return chain


def load_failover_chain(
    *,
    primary_label: str = "主配置",
    primary_client: Any = None,
    primary_base_url: str = "",
    primary_model_name: str = "",
    db_path: Optional[str] = None,
) -> List[Tuple[str, Any, str]]:
    """读取数据库中的启用档案并构建完整故障转移链。"""
    from src.infrastructure.persistence.sqlite_ai_profile_repository import (
        get_failover_profiles,
    )

    profiles = get_failover_profiles(db_path=db_path)
    return build_model_chain(
        primary_label=primary_label,
        primary_client=primary_client,
        primary_base_url=primary_base_url,
        primary_model_name=primary_model_name,
        profiles=profiles,
    )
