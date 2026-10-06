"""
设置管理路由
"""
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.dependencies import get_process_service
from src.infrastructure.config.env_manager import env_manager
from src.infrastructure.config.settings import (
    AISettings,
    reload_settings,
    scraper_settings,
)
from src.infrastructure.persistence.sqlite_ai_profile_repository import (
    create_ai_profile,
    delete_ai_profile,
    get_ai_profile,
    list_ai_profiles,
    update_ai_profile,
)
from src.services.ai_request_compat import (
    CHAT_COMPLETIONS_API_MODE,
    RESPONSES_API_MODE,
    build_ai_request_params,
    create_ai_response_sync,
    is_chat_completions_api_unsupported_error,
    is_responses_api_unsupported_error,
)
from src.services.ai_response_parser import extract_ai_response_content
from src.services.notification_config_service import (
    NotificationSettingsValidationError,
    build_configured_channels,
    build_notification_settings_response,
    build_notification_status_flags,
    load_notification_settings,
    model_dump,
    prepare_notification_test_settings,
    prepare_notification_settings_update,
)
from src.services.notification_service import build_notification_service
from src.services.process_service import ProcessService


router = APIRouter(prefix="/api/settings", tags=["settings"])
AI_TEST_PROMPT = "Reply with OK only."
AI_TEST_MAX_OUTPUT_TOKENS = 32


def _reload_env() -> None:
    load_dotenv(dotenv_path=env_manager.env_file, override=True)
    reload_settings()


def _env_bool(key: str, default: bool = False) -> bool:
    value = env_manager.get_value(key)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(key: str, default: int) -> int:
    value = env_manager.get_value(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _normalize_bool_value(value: bool) -> str:
    return "true" if value else "false"


class NotificationSettingsModel(BaseModel):
    """通知设置模型"""

    NTFY_TOPIC_URL: Optional[str] = None
    GOTIFY_URL: Optional[str] = None
    GOTIFY_TOKEN: Optional[str] = None
    BARK_URL: Optional[str] = None
    WX_BOT_URL: Optional[str] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    TELEGRAM_API_BASE_URL: Optional[str] = None
    WEBHOOK_URL: Optional[str] = None
    WEBHOOK_METHOD: Optional[str] = None
    WEBHOOK_HEADERS: Optional[str] = None
    WEBHOOK_CONTENT_TYPE: Optional[str] = None
    WEBHOOK_QUERY_PARAMETERS: Optional[str] = None
    WEBHOOK_BODY: Optional[str] = None
    PCURL_TO_MOBILE: Optional[bool] = None


class NotificationTestRequest(BaseModel):
    """通知测试请求"""

    channel: Optional[str] = None
    settings: NotificationSettingsModel = Field(default_factory=NotificationSettingsModel)


class AISettingsModel(BaseModel):
    """AI设置模型"""

    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    OPENAI_MODEL_NAME: Optional[str] = None
    SKIP_AI_ANALYSIS: Optional[bool] = None
    PROXY_URL: Optional[str] = None


class AIProfileCreateModel(BaseModel):
    """AI 模型档案创建模型"""

    name: str = Field(min_length=1, max_length=60)
    base_url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    proxy_url: Optional[str] = None


class AIProfileUpdateModel(BaseModel):
    """AI 模型档案更新模型"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    base_url: Optional[str] = Field(default=None, min_length=1)
    api_key: Optional[str] = Field(default=None, min_length=1)
    model_name: Optional[str] = Field(default=None, min_length=1)
    proxy_url: Optional[str] = None


class RotationSettingsModel(BaseModel):
    ACCOUNT_ROTATION_ENABLED: Optional[bool] = None
    ACCOUNT_ROTATION_MODE: Optional[str] = None
    ACCOUNT_ROTATION_RETRY_LIMIT: Optional[int] = None
    ACCOUNT_BLACKLIST_TTL: Optional[int] = None
    ACCOUNT_STATE_DIR: Optional[str] = None
    PROXY_ROTATION_ENABLED: Optional[bool] = None
    PROXY_ROTATION_MODE: Optional[str] = None
    PROXY_POOL: Optional[str] = None
    PROXY_ROTATION_RETRY_LIMIT: Optional[int] = None
    PROXY_BLACKLIST_TTL: Optional[int] = None


@router.get("/notifications")
async def get_notification_settings():
    return build_notification_settings_response(load_notification_settings())


@router.put("/notifications")
async def update_notification_settings(settings: NotificationSettingsModel):
    try:
        updates, deletions, merged_settings = prepare_notification_settings_update(
            model_dump(settings, exclude_unset=True),
            load_notification_settings(),
        )
    except NotificationSettingsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    success = env_manager.apply_changes(updates=updates, deletions=deletions)
    if not success:
        raise HTTPException(status_code=500, detail="更新通知设置失败")

    _reload_env()
    return {
        "message": "通知设置已成功更新",
        "configured_channels": build_configured_channels(merged_settings),
    }


@router.post("/notifications/test")
async def test_notification_settings(payload: NotificationTestRequest):
    try:
        merged_settings = prepare_notification_test_settings(
            model_dump(payload.settings, exclude_unset=True),
            load_notification_settings(),
            channel=payload.channel,
        )
    except NotificationSettingsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    service = build_notification_service(merged_settings)
    if not service.clients:
        if payload.channel:
            raise HTTPException(
                status_code=422,
                detail=f"渠道 {payload.channel} 未配置或不受支持",
            )
        raise HTTPException(status_code=422, detail="请至少配置一个可用的通知渠道")

    results = await service.send_test_notification()
    if payload.channel:
        if payload.channel not in results:
            raise HTTPException(
                status_code=422,
                detail=f"渠道 {payload.channel} 未配置或不受支持",
            )
        results = {payload.channel: results[payload.channel]}

    return {
        "message": "测试通知已执行",
        "results": results,
    }


@router.get("/rotation")
async def get_rotation_settings():
    return {
        "ACCOUNT_ROTATION_ENABLED": _env_bool("ACCOUNT_ROTATION_ENABLED", False),
        "ACCOUNT_ROTATION_MODE": env_manager.get_value("ACCOUNT_ROTATION_MODE", "per_task"),
        "ACCOUNT_ROTATION_RETRY_LIMIT": _env_int("ACCOUNT_ROTATION_RETRY_LIMIT", 2),
        "ACCOUNT_BLACKLIST_TTL": _env_int("ACCOUNT_BLACKLIST_TTL", 300),
        "ACCOUNT_STATE_DIR": env_manager.get_value("ACCOUNT_STATE_DIR", "state"),
        "PROXY_ROTATION_ENABLED": _env_bool("PROXY_ROTATION_ENABLED", False),
        "PROXY_ROTATION_MODE": env_manager.get_value("PROXY_ROTATION_MODE", "per_task"),
        "PROXY_POOL": env_manager.get_value("PROXY_POOL", ""),
        "PROXY_ROTATION_RETRY_LIMIT": _env_int("PROXY_ROTATION_RETRY_LIMIT", 2),
        "PROXY_BLACKLIST_TTL": _env_int("PROXY_BLACKLIST_TTL", 300),
    }


@router.put("/rotation")
async def update_rotation_settings(settings: RotationSettingsModel):
    updates = {}
    payload = model_dump(settings, exclude_unset=True)
    for key, value in payload.items():
        if isinstance(value, bool):
            updates[key] = _normalize_bool_value(value)
        else:
            updates[key] = str(value)
    success = env_manager.update_values(updates)
    if not success:
        raise HTTPException(status_code=500, detail="更新轮换设置失败")
    _reload_env()
    return {"message": "轮换设置已成功更新"}


@router.get("/status")
async def get_system_status(
    process_service: ProcessService = Depends(get_process_service),
):
    state_file = "xianyu_state.json"
    login_state_exists = os.path.exists(state_file)
    env_file_exists = os.path.exists(env_manager.env_file)
    openai_api_key = env_manager.get_value("OPENAI_API_KEY", "")
    openai_base_url = env_manager.get_value("OPENAI_BASE_URL", "")
    openai_model_name = env_manager.get_value("OPENAI_MODEL_NAME", "")
    ai_settings = AISettings()
    notification_settings = load_notification_settings()
    running_task_ids = [
        task_id
        for task_id, process in process_service.processes.items()
        if process and process.returncode is None
    ]

    return {
        "ai_configured": ai_settings.is_configured(),
        "notification_configured": notification_settings.has_any_notification_enabled(),
        "headless_mode": scraper_settings.run_headless,
        "running_in_docker": scraper_settings.running_in_docker,
        "scraper_running": len(running_task_ids) > 0,
        "running_task_ids": running_task_ids,
        "login_state_file": {
            "exists": login_state_exists,
            "path": state_file,
        },
        "env_file": {
            "exists": env_file_exists,
            "openai_api_key_set": bool(openai_api_key),
            "openai_base_url_set": bool(openai_base_url),
            "openai_model_name_set": bool(openai_model_name),
            **build_notification_status_flags(notification_settings),
        },
        "configured_notification_channels": build_configured_channels(notification_settings),
    }


@router.get("/ai")
async def get_ai_settings():
    return {
        "OPENAI_BASE_URL": env_manager.get_value("OPENAI_BASE_URL", ""),
        "OPENAI_MODEL_NAME": env_manager.get_value("OPENAI_MODEL_NAME", ""),
        "SKIP_AI_ANALYSIS": env_manager.get_value("SKIP_AI_ANALYSIS", "false").lower() == "true",
        "PROXY_URL": env_manager.get_value("PROXY_URL", ""),
    }


@router.put("/ai")
async def update_ai_settings(settings: AISettingsModel):
    updates = {}
    if settings.OPENAI_API_KEY is not None:
        updates["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    if settings.OPENAI_BASE_URL is not None:
        updates["OPENAI_BASE_URL"] = settings.OPENAI_BASE_URL
    if settings.OPENAI_MODEL_NAME is not None:
        updates["OPENAI_MODEL_NAME"] = settings.OPENAI_MODEL_NAME
    if settings.SKIP_AI_ANALYSIS is not None:
        updates["SKIP_AI_ANALYSIS"] = str(settings.SKIP_AI_ANALYSIS).lower()
    if settings.PROXY_URL is not None:
        updates["PROXY_URL"] = settings.PROXY_URL

    success = env_manager.update_values(updates)
    if not success:
        raise HTTPException(status_code=500, detail="更新AI设置失败")
    _reload_env()
    return {"message": "AI设置已成功更新"}


@router.post("/ai/test")
async def test_ai_settings(settings: dict):
    """测试AI模型设置是否有效"""
    try:
        from openai import OpenAI
        import httpx

        stored_api_key = env_manager.get_value("OPENAI_API_KEY", "")
        submitted_api_key = settings.get("OPENAI_API_KEY", "")
        api_key = submitted_api_key or stored_api_key

        client_params = {
            "api_key": api_key,
            "base_url": settings.get("OPENAI_BASE_URL", ""),
            "timeout": httpx.Timeout(30.0),
        }

        proxy_url = settings.get("PROXY_URL", "")
        if proxy_url:
            client_params["http_client"] = httpx.Client(proxy=proxy_url)

        model_name = settings.get("OPENAI_MODEL_NAME", "")
        client = OpenAI(**client_params)
        messages = [{"role": "user", "content": AI_TEST_PROMPT}]
        api_mode = CHAT_COMPLETIONS_API_MODE

        try:
            response = create_ai_response_sync(
                client,
                api_mode,
                build_ai_request_params(
                    api_mode,
                    model=model_name,
                    messages=messages,
                    max_output_tokens=AI_TEST_MAX_OUTPUT_TOKENS,
                ),
            )
        except Exception as exc:
            if not is_chat_completions_api_unsupported_error(exc):
                raise
            api_mode = RESPONSES_API_MODE
            response = create_ai_response_sync(
                client,
                api_mode,
                build_ai_request_params(
                    api_mode,
                    model=model_name,
                    messages=messages,
                    max_output_tokens=AI_TEST_MAX_OUTPUT_TOKENS,
                ),
            )

        return {
            "success": True,
            "message": "AI模型连接测试成功！",
            "response": extract_ai_response_content(response),
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"AI模型连接测试失败: {exc}",
        }


def _mask_api_key(key: str) -> str:
    """对 API Key 做掩码，仅返回前 3 位 + 尾 4 位。"""
    key = key or ""
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"


def _profile_public(profile: dict) -> dict:
    """去掉完整 api_key，只返回掩码。"""
    return {
        "id": profile["id"],
        "name": profile["name"],
        "base_url": profile["base_url"],
        "api_key_masked": _mask_api_key(profile.get("api_key") or ""),
        "model_name": profile["model_name"],
        "proxy_url": profile.get("proxy_url") or "",
        "created_at": profile.get("created_at"),
        "updated_at": profile.get("updated_at"),
    }


@router.get("/ai/profiles")
async def get_ai_profiles():
    profiles = list_ai_profiles()
    return {"profiles": [_profile_public(p) for p in profiles]}


@router.post("/ai/profiles")
async def add_ai_profile(payload: AIProfileCreateModel):
    try:
        profile = create_ai_profile(
            name=payload.name,
            base_url=payload.base_url,
            api_key=payload.api_key,
            model_name=payload.model_name,
            proxy_url=payload.proxy_url,
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(
                status_code=409, detail=f"档案名称「{payload.name}」已存在，请换一个名称。"
            ) from exc
        raise HTTPException(status_code=500, detail=f"保存模型档案失败: {exc}") from exc
    return {"message": "模型档案已保存", "profile": _profile_public(profile)}


@router.put("/ai/profiles/{profile_id}")
async def edit_ai_profile(profile_id: int, payload: AIProfileUpdateModel):
    profile = update_ai_profile(
        profile_id,
        name=payload.name,
        base_url=payload.base_url,
        api_key=payload.api_key,
        model_name=payload.model_name,
        proxy_url=payload.proxy_url,
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="模型档案不存在")
    return {"message": "模型档案已更新", "profile": _profile_public(profile)}


@router.delete("/ai/profiles/{profile_id}")
async def remove_ai_profile(profile_id: int):
    if not delete_ai_profile(profile_id):
        raise HTTPException(status_code=404, detail="模型档案不存在")
    return {"message": "模型档案已删除"}


@router.post("/ai/profiles/{profile_id}/apply")
async def apply_ai_profile(profile_id: int):
    """将某个已保存的模型档案应用到当前生效配置（写入 .env 并热重载）。"""
    profile = get_ai_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="模型档案不存在")

    updates = {
        "OPENAI_API_KEY": profile["api_key"],
        "OPENAI_BASE_URL": profile["base_url"],
        "OPENAI_MODEL_NAME": profile["model_name"],
        "PROXY_URL": profile.get("proxy_url") or "",
    }
    success = env_manager.update_values(updates)
    if not success:
        raise HTTPException(status_code=500, detail="应用模型档案失败（写入 .env 出错）")
    _reload_env()
    return {
        "message": f"已切换到模型档案「{profile['name']}」",
        "profile": _profile_public(profile),
        "active_settings": {
            "OPENAI_BASE_URL": env_manager.get_value("OPENAI_BASE_URL", ""),
            "OPENAI_MODEL_NAME": env_manager.get_value("OPENAI_MODEL_NAME", ""),
            "PROXY_URL": env_manager.get_value("PROXY_URL", ""),
        },
    }
