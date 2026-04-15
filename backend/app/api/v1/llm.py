"""
LLM API endpoints.
"""

import random
import re
import time
from collections import defaultdict
from contextlib import asynccontextmanager

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user_from_token, require_admin, require_automation_role, require_backup_role
from app.models.user import User
from app.modules.llm.schemas import (
    AddDirectSkillRequest,
    AddGitRepoRequest,
    AuditLogSummaryRequest,
    BackupListSummaryRequest,
    CategorySelectionRequest,
    CategorySelectionResponse,
    ChatResponse,
    ConversationMessageResponse,
    ConversationThreadDetail,
    ConversationThreadListResponse,
    ConversationThreadSummary,
    DashboardSummaryRequest,
    DebugExecutionRequest,
    DebugExecutionResponse,
    ElicitationResponseRequest,
    FieldAssistRequest,
    FieldAssistResponse,
    FollowUpRequest,
    GlobalChatRequest,
    GlobalChatResponse,
    LLMConfigAvailable,
    LLMConfigCreate,
    LLMConfigResponse,
    LLMConfigUpdate,
    LLMConnectionTestRequest,
    LLMModelDiscoveryRequest,
    MCPConfigAvailable,
    MCPConfigCreate,
    MCPConfigResponse,
    MCPConfigUpdate,
    MCPConnectionTestRequest,
    McpToolCallRequest,
    MemoryEntryResponse,
    MemoryListResponse,
    MemoryUpdateRequest,
    SkillGitRepoResponse,
    SkillMcpServerUpdateRequest,
    SkillResponse,
    SummarizeDiffRequest,
    SummaryResponse,
    SystemLogSummaryRequest,
    WebhookSummaryRequest,
    WebhookSummaryResponse,
    WorkflowAssistRequest,
    WorkflowAssistResponse,
)
from app.modules.llm.services.llm_service_factory import _LOCAL_PROVIDERS

router = APIRouter()
logger = structlog.get_logger(__name__)


def _parse_oid(value: str, label: str = "ID") -> PydanticObjectId:
    """Parse a string to PydanticObjectId, raising 400 on invalid format."""
    try:
        return PydanticObjectId(value)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {label}") from exc


# ── LLM rate limiter (per-user sliding window) ───────────────────────────────
_llm_requests: dict[str, list[float]] = defaultdict(list)
_LLM_RATE_WINDOW = 60  # 1 minute
_LLM_RATE_MAX = 20  # max requests per window


def _sanitize_prior_turn(content: str, max_len: int) -> str:
    """Truncate and strip prompt-injection markers from prior conversation turns."""
    text = content[:max_len]
    return text.replace("```", "").replace("---", "").replace("***", "")


def _check_llm_rate_limit(user_id: str) -> None:
    """Raise 429 if the user has exceeded the LLM rate limit."""
    now = time.monotonic()

    # Probabilistic cleanup of stale entries to prevent unbounded memory growth
    # from users who stop making requests. Runs ~1% of the time.
    if random.random() < 0.01:
        for uid in list(_llm_requests.keys()):
            _llm_requests[uid] = [t for t in _llm_requests[uid] if now - t < _LLM_RATE_WINDOW]
            if not _llm_requests[uid]:
                del _llm_requests[uid]

    recent = [t for t in _llm_requests[user_id] if now - t < _LLM_RATE_WINDOW]
    if not recent:
        _llm_requests.pop(user_id, None)
    else:
        _llm_requests[user_id] = recent
    if len(recent) >= _LLM_RATE_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many LLM requests. Please wait before trying again.",
        )
    _llm_requests[user_id].append(now)


async def _get_canvas_instructions() -> str:
    """Load the effective canvas tier from the default LLM config and return instructions."""
    from app.modules.llm.models import LLMConfig as LLMConfigModel
    from app.modules.llm.services.llm_service_factory import get_effective_canvas_tier
    from app.modules.llm.services.prompt_builders import build_canvas_instructions

    default_config = await LLMConfigModel.find_one(
        LLMConfigModel.is_default == True, LLMConfigModel.enabled == True
    )  # noqa: E712
    if not default_config:
        return ""
    return build_canvas_instructions(get_effective_canvas_tier(default_config))


async def _load_external_mcp_clients(config_ids: list[str]) -> list:
    """Load external MCP clients, wrapping SSRF errors as HTTP 400."""
    from app.modules.llm.services.mcp_client import load_external_mcp_clients

    try:
        return await load_external_mcp_clients(config_ids)
    except ValueError as e:
        logger.warning("mcp_ssrf_blocked", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"MCP server URL blocked by security policy: {e}",
        ) from None


@asynccontextmanager
async def _mcp_user_session(
    user_id: str,
    elicitation_channel: str | None = None,
    extra_clients: list | None = None,
    thread_id: str | None = None,
):
    """Context manager that sets MCP user context, connects clients, and cleans up.

    Always includes the local in-process MCP server. ``extra_clients`` are
    additional (external) MCPClientWrapper instances to connect alongside.
    """
    from app.modules.llm.services.mcp_client import create_local_mcp_client
    from app.modules.mcp_server.helpers import elicitation_channel_var
    from app.modules.mcp_server.server import mcp_thread_id_var, mcp_user_id_var

    token_user = mcp_user_id_var.set(str(user_id))
    token_elicit = elicitation_channel_var.set(elicitation_channel)
    token_thread = mcp_thread_id_var.set(thread_id)

    local = create_local_mcp_client()
    all_clients = [local] + (extra_clients or [])
    try:
        # Connect sequentially — asyncio.gather creates separate tasks which
        # breaks anyio cancel scopes used by MCP streamable HTTP transport.
        for c in all_clients:
            await c.connect()
    except BaseException:
        for c in all_clients:
            await c.disconnect()
        mcp_user_id_var.reset(token_user)
        elicitation_channel_var.reset(token_elicit)
        mcp_thread_id_var.reset(token_thread)
        raise
    try:
        yield all_clients
    finally:
        for c in all_clients:
            await c.disconnect()
        mcp_user_id_var.reset(token_user)
        elicitation_channel_var.reset(token_elicit)
        mcp_thread_id_var.reset(token_thread)


# ── Status & Test ─────────────────────────────────────────────────────────────


@router.get("/llm/status", tags=["LLM"])
async def get_llm_status(_current_user: User = Depends(get_current_user_from_token)):
    """Check if LLM features are available (using the default config)."""
    from app.models.system import SystemConfig
    from app.modules.llm.models import LLMConfig

    sys_config = await SystemConfig.get_config()
    if not sys_config.llm_enabled:
        return {"enabled": False, "provider": None, "model": None}

    default = await LLMConfig.find_one(LLMConfig.is_default == True, LLMConfig.enabled == True)  # noqa: E712
    if not default or not default.api_key:
        return {"enabled": False, "provider": None, "model": None}

    return {
        "enabled": True,
        "provider": default.provider,
        "model": default.model,
    }


@router.post("/llm/test", tags=["LLM"])
async def test_llm_connection(_current_user: User = Depends(get_current_user_from_token)):
    """Test LLM connection by sending a simple prompt."""
    from app.modules.llm.services.llm_service import LLMMessage
    from app.modules.llm.services.llm_service_factory import create_llm_service

    try:
        llm = await create_llm_service()
        response = await llm.complete([LLMMessage(role="user", content="Reply with exactly: OK")])
        return {
            "status": "connected",
            "model": response.model,
            "response": response.content[:100],
        }
    except Exception as e:
        logger.warning("llm_test_failed", error=str(e))
        return {"status": "error", "error": "LLM connection test failed. Check your configuration."}


# ── LLM Config CRUD ──────────────────────────────────────────────────────────


def _config_to_response(cfg) -> LLMConfigResponse:
    from app.modules.llm.services.llm_service_factory import get_effective_canvas_tier
    from app.modules.llm.services.token_service import resolve_context_window

    return LLMConfigResponse(
        id=str(cfg.id),
        name=cfg.name,
        provider=cfg.provider,
        api_key_set=bool(cfg.api_key),
        model=cfg.model,
        base_url=cfg.base_url,
        temperature=cfg.temperature,
        max_tokens_per_request=cfg.max_tokens_per_request,
        context_window_tokens=cfg.context_window_tokens,
        context_window_effective=resolve_context_window(cfg.context_window_tokens, cfg.model),
        is_default=cfg.is_default,
        enabled=cfg.enabled,
        canvas_prompt_tier=cfg.canvas_prompt_tier,
        canvas_prompt_tier_effective=get_effective_canvas_tier(cfg),
    )


@router.get("/llm/configs", tags=["LLM"])
async def list_llm_configs(_current_user: User = Depends(require_admin)):
    """List all LLM configurations."""
    from app.modules.llm.models import LLMConfig

    configs = await LLMConfig.find_all().to_list()
    return [_config_to_response(c) for c in configs]


@router.post("/llm/configs", tags=["LLM"])
async def create_llm_config(
    request: LLMConfigCreate,
    _current_user: User = Depends(require_admin),
):
    """Create a new LLM configuration."""
    from app.core.security import encrypt_sensitive_data
    from app.modules.llm.models import LLMConfig

    # If setting as default, unset any existing default
    if request.is_default:
        await LLMConfig.find(LLMConfig.is_default == True).update_many({"$set": {"is_default": False}})  # noqa: E712

    cfg = LLMConfig(
        name=request.name,
        provider=request.provider,
        api_key=encrypt_sensitive_data(request.api_key) if request.api_key else None,
        model=request.model,
        base_url=request.base_url,
        temperature=request.temperature,
        max_tokens_per_request=request.max_tokens_per_request,
        context_window_tokens=request.context_window_tokens,
        is_default=request.is_default,
        enabled=request.enabled,
        canvas_prompt_tier=request.canvas_prompt_tier,
    )
    await cfg.insert()
    return _config_to_response(cfg)


@router.put("/llm/configs/{config_id}", tags=["LLM"])
async def update_llm_config(
    config_id: str,
    request: LLMConfigUpdate,
    _current_user: User = Depends(require_admin),
):
    """Update an LLM configuration."""
    from app.core.security import encrypt_sensitive_data
    from app.modules.llm.models import LLMConfig

    cfg = await LLMConfig.get(_parse_oid(config_id, "config ID"))
    if not cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    updates = request.model_dump(exclude_unset=True)

    # Encrypt API key if provided
    if "api_key" in updates and updates["api_key"]:
        updates["api_key"] = encrypt_sensitive_data(updates["api_key"])
    elif "api_key" in updates and not updates["api_key"]:
        del updates["api_key"]  # Don't clear existing key when empty string sent

    # If setting as default, unset any existing default
    if updates.get("is_default"):
        await LLMConfig.find(LLMConfig.is_default == True, LLMConfig.id != cfg.id).update_many(  # noqa: E712
            {"$set": {"is_default": False}}
        )

    for field, value in updates.items():
        setattr(cfg, field, value)
    cfg.update_timestamp()
    await cfg.save()
    return _config_to_response(cfg)


@router.delete("/llm/configs/{config_id}", tags=["LLM"])
async def delete_llm_config(
    config_id: str,
    _current_user: User = Depends(require_admin),
):
    """Delete an LLM configuration (cannot delete the default)."""
    from app.modules.llm.models import LLMConfig

    cfg = await LLMConfig.get(_parse_oid(config_id, "config ID"))
    if not cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")
    if cfg.is_default:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete the default config")

    await cfg.delete()
    return {"status": "deleted"}


@router.post("/llm/configs/{config_id}/set-default", tags=["LLM"])
async def set_default_llm_config(
    config_id: str,
    _current_user: User = Depends(require_admin),
):
    """Set an LLM configuration as the default."""
    from app.modules.llm.models import LLMConfig

    cfg = await LLMConfig.get(_parse_oid(config_id, "config ID"))
    if not cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    # Unset all defaults, then set this one
    await LLMConfig.find(LLMConfig.is_default == True).update_many({"$set": {"is_default": False}})  # noqa: E712
    cfg.is_default = True
    cfg.update_timestamp()
    await cfg.save()
    return _config_to_response(cfg)


@router.post("/llm/configs/{config_id}/test", tags=["LLM"])
async def test_llm_config(
    config_id: str,
    _current_user: User = Depends(require_admin),
):
    """Test a specific LLM configuration's connection."""
    from app.modules.llm.services.llm_service import LLMMessage
    from app.modules.llm.services.llm_service_factory import create_llm_service

    try:
        llm = await create_llm_service(config_id=config_id)
        response = await llm.complete([LLMMessage(role="user", content="Reply with exactly: OK")])
        return {"status": "connected", "model": response.model, "response": response.content[:100]}
    except Exception as e:
        logger.warning("llm_config_test_failed", config_id=config_id, error=str(e))
        return {"status": "error", "error": "Connection test failed. Check your configuration."}


async def _resolve_api_key(api_key: str | None, config_id: str | None) -> str:
    """Get the API key from the request or from a stored config."""
    if api_key:
        return api_key
    if config_id:
        from app.core.security import decrypt_sensitive_data
        from app.modules.llm.models import LLMConfig

        cfg = await LLMConfig.get(_parse_oid(config_id, "config ID"))
        if cfg and cfg.api_key:
            return decrypt_sensitive_data(cfg.api_key)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API key required")


@router.post("/llm/test-connection", tags=["LLM"])
async def test_connection_anonymous(
    request: LLMConnectionTestRequest,
    _current_user: User = Depends(require_admin),
):
    """Test LLM connection with unsaved config values."""
    from app.modules.llm.services.llm_service import LLMMessage, LLMService
    from app.modules.llm.services.llm_service_factory import _default_model

    api_key = await _resolve_api_key(request.api_key, request.config_id)
    if request.base_url and request.provider not in _LOCAL_PROVIDERS:
        from app.utils.url_safety import validate_outbound_url

        validate_outbound_url(request.base_url)
    try:
        model = _default_model(request.provider)
        # For providers that serve a dynamically-named model, discover it at runtime
        if request.provider in {"vllm", "lm_studio", "llama_cpp"}:
            discovered = await _fetch_models(request.provider, api_key or "", request.base_url)
            if discovered:
                model = discovered[0]["id"]
        llm = LLMService(
            provider=request.provider,
            api_key=api_key,
            model=model,
            base_url=request.base_url,
        )
        response = await llm.complete([LLMMessage(role="user", content="Reply with exactly: OK")])
        return {"status": "connected", "model": response.model, "response": response.content[:100]}
    except Exception as e:
        logger.warning("llm_test_connection_failed", error=str(e))
        return {"status": "error", "error": "Connection test failed. Check your configuration."}


@router.post("/llm/discover-models", tags=["LLM"])
async def discover_models_anonymous(
    request: LLMModelDiscoveryRequest,
    _current_user: User = Depends(require_admin),
):
    """Discover available models with unsaved config values."""
    if request.base_url and request.provider not in _LOCAL_PROVIDERS:
        from app.utils.url_safety import validate_outbound_url

        validate_outbound_url(request.base_url)
    api_key = await _resolve_api_key(request.api_key, request.config_id)
    models = await _fetch_models(request.provider, api_key, request.base_url)
    return {"models": models}


@router.get("/llm/configs/available", tags=["LLM"])
async def list_available_configs(_current_user: User = Depends(get_current_user_from_token)):
    """List LLM configs available for workflow creators (no secrets)."""
    from app.modules.llm.models import LLMConfig

    configs = await LLMConfig.find(LLMConfig.enabled == True).to_list()  # noqa: E712
    return [
        LLMConfigAvailable(id=str(c.id), name=c.name, provider=c.provider, model=c.model, is_default=c.is_default)
        for c in configs
    ]


@router.get("/llm/configs/{config_id}/models", tags=["LLM"])
async def list_config_models(
    config_id: str,
    _current_user: User = Depends(require_admin),
):
    """Fetch available models from the provider."""
    from app.core.security import decrypt_sensitive_data
    from app.modules.llm.models import LLMConfig

    cfg = await LLMConfig.get(_parse_oid(config_id, "config ID"))
    if not cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")
    if not cfg.api_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API key not configured")

    if cfg.base_url and cfg.provider not in _LOCAL_PROVIDERS:
        from app.utils.url_safety import validate_outbound_url

        validate_outbound_url(cfg.base_url)
    api_key = decrypt_sensitive_data(cfg.api_key)
    models = await _fetch_models(cfg.provider, api_key, cfg.base_url)
    return {"models": models}


async def _fetch_models(provider: str, api_key: str, base_url: str | None) -> list[dict]:
    """Fetch available models from a provider. Returns [{id, name, context_window}]."""
    import httpx

    from app.modules.llm.services.token_service import get_context_window

    try:
        if provider in ("openai", "azure_openai", "lm_studio", "ollama", "llama_cpp", "vllm", "mistral"):
            from openai import AsyncOpenAI
            from app.modules.llm.services.llm_service import _build_openai_client_kwargs

            url = base_url
            if provider == "lm_studio" and not url:
                url = "http://localhost:1234/v1"
            if provider == "llama_cpp" and not url:
                url = "http://localhost:8080/v1"

            client_kwargs, custom_http_client = _build_openai_client_kwargs(provider, api_key, url)
            client = AsyncOpenAI(**client_kwargs)
            try:
                result = await client.models.list()
                return [{"id": m.id, "name": m.id, "context_window": get_context_window(m.id)} for m in result.data]
            finally:
                try:
                    await client.close()
                finally:
                    if custom_http_client is not None and not getattr(custom_http_client, "is_closed", True):
                        await custom_http_client.aclose()

        elif provider == "anthropic":
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                )
                resp.raise_for_status()
                data = resp.json()
                return [
                    {
                        "id": m["id"],
                        "name": m.get("display_name", m["id"]),
                        "context_window": get_context_window(f"anthropic/{m['id']}"),
                    }
                    for m in data.get("data", [])
                ]

        else:
            # Bedrock, Vertex — hardcoded
            return []

    except Exception as e:
        logger.warning("model_discovery_failed", provider=provider, error=str(e))
        return []


# ── MCP Config CRUD ──────────────────────────────────────────────────────────


def _mcp_config_to_response(cfg) -> MCPConfigResponse:
    import json as json_mod

    from app.core.security import decrypt_sensitive_data

    headers = None
    if cfg.headers:
        try:
            parsed = json_mod.loads(decrypt_sensitive_data(cfg.headers))
            headers = {k: "••••••••" for k in parsed}  # Mask values, show keys only
        except Exception:
            pass  # Decryption failure — return None, headers_set still shows True
    return MCPConfigResponse(
        id=str(cfg.id),
        name=cfg.name,
        url=cfg.url,
        headers=headers,
        headers_set=bool(cfg.headers),
        ssl_verify=cfg.ssl_verify,
        enabled=cfg.enabled,
    )


@router.get("/mcp/configs", tags=["MCP"])
async def list_mcp_configs(_current_user: User = Depends(require_admin)):
    """List all MCP server configurations."""
    from app.modules.llm.models import MCPConfig

    configs = await MCPConfig.find_all().to_list()
    return [_mcp_config_to_response(c) for c in configs]


@router.post("/mcp/configs", tags=["MCP"])
async def create_mcp_config(
    request: MCPConfigCreate,
    _current_user: User = Depends(require_admin),
):
    """Create a new MCP server configuration."""
    import json as json_mod

    from app.core.security import encrypt_sensitive_data
    from app.modules.llm.models import MCPConfig

    cfg = MCPConfig(
        name=request.name,
        url=request.url,
        headers=encrypt_sensitive_data(json_mod.dumps(request.headers)) if request.headers else None,
        ssl_verify=request.ssl_verify,
        enabled=request.enabled,
    )
    await cfg.insert()
    return _mcp_config_to_response(cfg)


@router.put("/mcp/configs/{config_id}", tags=["MCP"])
async def update_mcp_config(
    config_id: str,
    request: MCPConfigUpdate,
    _current_user: User = Depends(require_admin),
):
    """Update an MCP server configuration."""
    import json as json_mod

    from app.core.security import encrypt_sensitive_data
    from app.modules.llm.models import MCPConfig

    cfg = await MCPConfig.get(_parse_oid(config_id, "config ID"))
    if not cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP config not found")

    updates = request.model_dump(exclude_unset=True)

    if "headers" in updates and updates["headers"]:
        updates["headers"] = encrypt_sensitive_data(json_mod.dumps(updates["headers"]))
    elif "headers" in updates and not updates["headers"]:
        del updates["headers"]

    for field, value in updates.items():
        setattr(cfg, field, value)
    cfg.update_timestamp()
    await cfg.save()
    return _mcp_config_to_response(cfg)


@router.delete("/mcp/configs/{config_id}", tags=["MCP"])
async def delete_mcp_config(
    config_id: str,
    _current_user: User = Depends(require_admin),
):
    """Delete an MCP server configuration."""
    from app.modules.llm.models import MCPConfig

    cfg = await MCPConfig.get(_parse_oid(config_id, "config ID"))
    if not cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP config not found")
    await cfg.delete()
    return {"status": "deleted"}


@router.post("/mcp/configs/{config_id}/test", tags=["MCP"])
async def test_mcp_config(
    config_id: str,
    _current_user: User = Depends(require_admin),
):
    """Test connection to an MCP server."""
    import json as json_mod

    from app.core.security import decrypt_sensitive_data
    from app.modules.llm.models import MCPConfig
    from app.modules.llm.services.mcp_client import MCPClientWrapper, MCPServerConfig

    cfg = await MCPConfig.get(_parse_oid(config_id, "config ID"))
    if not cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP config not found")

    from app.utils.url_safety import validate_outbound_url

    validate_outbound_url(cfg.url)
    headers = json_mod.loads(decrypt_sensitive_data(cfg.headers)) if cfg.headers else None
    client = MCPClientWrapper(MCPServerConfig(name=cfg.name, url=cfg.url, headers=headers, ssl_verify=cfg.ssl_verify))
    try:
        await client.connect()
        tools = await client.list_tools()
        return {"status": "connected", "tools": len(tools), "tool_names": [t.name for t in tools[:20]]}
    except BaseException as e:
        logger.warning("mcp_config_test_failed", config_id=config_id, error=str(e), error_type=type(e).__name__)
        return {"status": "error", "error": f"Connection test failed: {type(e).__name__}. Check URL and credentials."}
    finally:
        await client.disconnect()


@router.get("/mcp/configs/available", tags=["MCP"])
async def list_available_mcp_configs(_current_user: User = Depends(get_current_user_from_token)):
    """List MCP configs available for workflow creators (no secrets)."""
    from app.modules.llm.models import MCPConfig

    configs = await MCPConfig.find(MCPConfig.enabled == True).to_list()  # noqa: E712
    return [MCPConfigAvailable(id=str(c.id), name=c.name, url=c.url) for c in configs]


@router.post("/mcp/test-connection", tags=["MCP"])
async def test_mcp_connection_anonymous(
    request: MCPConnectionTestRequest,
    _current_user: User = Depends(require_admin),
):
    """Test MCP connection with unsaved config values."""
    import json as json_mod

    from app.modules.llm.services.mcp_client import MCPClientWrapper, MCPServerConfig

    headers = request.headers
    if not headers and request.config_id:
        from app.core.security import decrypt_sensitive_data
        from app.modules.llm.models import MCPConfig

        cfg = await MCPConfig.get(_parse_oid(request.config_id, "config ID"))
        if cfg and cfg.headers:
            headers = json_mod.loads(decrypt_sensitive_data(cfg.headers))

    from app.utils.url_safety import validate_outbound_url

    validate_outbound_url(request.url)
    client = MCPClientWrapper(
        MCPServerConfig(name="test", url=request.url, headers=headers, ssl_verify=request.ssl_verify)
    )
    try:
        await client.connect()
        tools = await client.list_tools()
        return {"status": "connected", "tools": len(tools), "tool_names": [t.name for t in tools[:20]]}
    except BaseException as e:
        logger.warning("mcp_test_connection_failed", error=str(e), error_type=type(e).__name__)
        return {"status": "error", "error": f"Connection test failed: {type(e).__name__}. Check URL and credentials."}
    finally:
        await client.disconnect()


# ── MCP Tool Browser & Test ──────────────────────────────────────────────────


@router.get("/mcp/configs/{config_id}/tools", tags=["MCP"])
async def list_mcp_config_tools(
    config_id: str,
    _current_user: User = Depends(require_admin),
):
    """List all tools from an external MCP server with full schemas."""
    clients = await _load_external_mcp_clients([config_id])
    if not clients:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP config not found or disabled")

    client = clients[0]
    try:
        await client.connect()
        tools = await client.list_tools()
        return [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
    except BaseException as e:
        logger.warning("mcp_list_tools_failed", config_id=config_id, error=str(e), error_type=type(e).__name__)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to MCP server") from None
    finally:
        await client.disconnect()


@router.post("/mcp/configs/{config_id}/tools/{tool_name}/call", tags=["MCP"])
async def call_mcp_config_tool(
    config_id: str,
    tool_name: str,
    request: McpToolCallRequest,
    _current_user: User = Depends(require_admin),
):
    """Call a specific tool on an external MCP server. Admin only."""
    clients = await _load_external_mcp_clients([config_id])
    if not clients:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP config not found or disabled")

    client = clients[0]
    try:
        await client.connect()
        result = await client.call_tool(tool_name, request.arguments)
        return {"result": result}
    except BaseException as e:
        logger.warning(
            "mcp_tool_call_failed", config_id=config_id, tool=tool_name, error=str(e), error_type=type(e).__name__
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Tool call failed. Check server connection and arguments.",
        ) from None
    finally:
        await client.disconnect()


@router.get("/mcp/local/tools", tags=["MCP"])
async def list_local_mcp_tools(
    current_user: User = Depends(require_admin),
):
    """List all tools from the local in-process MCP server."""
    from app.modules.llm.services.mcp_client import create_local_mcp_client
    from app.modules.mcp_server.server import mcp_user_id_var

    token_user = mcp_user_id_var.set(str(current_user.id))
    client = create_local_mcp_client()
    try:
        await client.connect()
        tools = await client.list_tools()
        return [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
    except BaseException as e:
        logger.warning("mcp_local_list_tools_failed", error=str(e), error_type=type(e).__name__)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to list local MCP tools") from None
    finally:
        await client.disconnect()
        mcp_user_id_var.reset(token_user)


@router.post("/mcp/local/tools/{tool_name}/call", tags=["MCP"])
async def call_local_mcp_tool(
    tool_name: str,
    request: McpToolCallRequest,
    current_user: User = Depends(require_admin),
):
    """Call a specific tool on the local MCP server. Admin only."""
    from app.modules.llm.services.mcp_client import create_local_mcp_client
    from app.modules.mcp_server.server import mcp_user_id_var

    token_user = mcp_user_id_var.set(str(current_user.id))
    client = create_local_mcp_client()
    try:
        await client.connect()
        result = await client.call_tool(tool_name, request.arguments)
        return {"result": result}
    except BaseException as e:
        logger.warning("mcp_local_tool_call_failed", tool=tool_name, error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Tool call failed.",
        ) from None
    finally:
        await client.disconnect()
        mcp_user_id_var.reset(token_user)


# ── Backup Summarization ─────────────────────────────────────────────────────


@router.post("/llm/backup/summarize", response_model=SummaryResponse, tags=["LLM"])
async def summarize_backup_change(
    request: SummarizeDiffRequest,
    current_user: User = Depends(require_backup_role),
):
    """Generate an LLM summary of changes between two backup object versions.

    Uses the MCP agent loop so the LLM can fetch additional backup data on demand.
    """
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.services.agent_service import AIAgentService
    from app.modules.llm.services.context_service import get_backup_diff_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_backup_summary_prompt

    llm = await create_llm_service()
    ctx = await get_backup_diff_context(request.version_id_1, request.version_id_2)

    prompt_messages = build_backup_summary_prompt(
        diff_entries=ctx["diff_entries"],
        object_type=ctx["object_type"],
        object_name=ctx["object_name"],
        old_version=ctx["old_version"],
        new_version=ctx["new_version"],
        event_type=ctx["event_type"],
        changed_fields=ctx["changed_fields"],
        version_id_1=request.version_id_1,
        version_id_2=request.version_id_2,
        object_id=ctx.get("object_id", ""),
        tz_name=current_user.timezone,
    )
    canvas_instr = await _get_canvas_instructions()
    if canvas_instr and prompt_messages and prompt_messages[0]["role"] == "system":
        prompt_messages[0]["content"] += "\n\n" + canvas_instr
    from app.modules.llm.services.skills_service import append_skills_to_messages, build_skills_catalog

    catalog = await build_skills_catalog()
    prompt_messages = append_skills_to_messages(prompt_messages, catalog)

    thread = await _load_or_create_thread(
        request.thread_id, current_user.id, "backup_summary", prompt_messages, context_ref=request.version_id_2
    )

    # Run agent with local MCP server
    async with _mcp_user_session(current_user.id) as mcp_clients:
        agent = AIAgentService(llm=llm, mcp_clients=mcp_clients, max_iterations=5)
        result = await agent.run(
            task=prompt_messages[-1]["content"],
            system_prompt=prompt_messages[0]["content"],
        )
        summary = result.result

    # Store assistant reply
    thread.add_message("assistant", summary)
    await thread.save()

    return SummaryResponse(
        summary=summary,
        thread_id=str(thread.id),
        usage=_usage_dict_from_agent(result),
    )


# ── Conversation Follow-Up ───────────────────────────────────────────────────


# Features whose follow-up messages should go through the MCP agent loop
_MCP_ENABLED_FEATURES = {"backup_summary", "global_chat", "impact_analysis_chat"}


@router.post("/llm/chat/{thread_id}", response_model=ChatResponse, tags=["LLM"])
async def continue_conversation(
    thread_id: str,
    request: FollowUpRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    """Continue an existing LLM conversation thread.

    Threads from MCP-enabled features (backup_summary, global_chat) route through
    the agent loop with MCP tools so the LLM can fetch data on demand.
    """
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.models import ConversationThread
    from app.modules.llm.services.llm_service_factory import create_llm_service

    try:
        thread = await ConversationThread.get(PydanticObjectId(thread_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid thread ID") from exc

    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation thread not found")
    if thread.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Thread not owned by user")

    # Update MCP server selection if the client sent an override
    if request.mcp_config_ids is not None and request.mcp_config_ids != thread.mcp_config_ids:
        thread.mcp_config_ids = request.mcp_config_ids
        logger.info("mcp_config_updated_mid_conversation", thread_id=str(thread.id), mcp_ids=request.mcp_config_ids)

    # Add user message and persist before LLM call (so it's not lost on failure)
    thread.add_message("user", request.message)
    await thread.save()

    tool_calls_summary: list[dict] = []
    msg_metadata = None
    if thread.feature in _MCP_ENABLED_FEATURES:
        agent_result = await _continue_with_mcp(thread, request.message, current_user, stream_id=request.stream_id)
        reply = agent_result.result
        tool_calls_summary = [{"tool": tc.tool, "arguments": tc.arguments} for tc in agent_result.tool_calls]
        msg_metadata = _agent_result_metadata(agent_result)
    else:
        llm = await create_llm_service()
        llm_messages = thread.to_llm_messages()
        response = await _stream_or_complete(llm, llm_messages, stream_id=request.stream_id)
        reply = response.content
        await _log_llm_usage(current_user.id, thread.feature, llm, response)

    # Store assistant reply
    thread.add_message("assistant", reply, metadata=msg_metadata)
    await thread.save()

    # Check if compaction is needed (background task, non-blocking)
    await _maybe_trigger_compaction(thread)

    return ChatResponse(
        reply=reply,
        thread_id=str(thread.id),
        tool_calls=tool_calls_summary,
        usage={},
    )


async def _continue_with_mcp(thread, message: str, current_user: User, stream_id: str | None = None):
    """Run a follow-up message through the MCP agent loop with conversation history.

    Returns an ``AgentResult`` so callers can access tool_calls.
    """
    from app.modules.llm.services.agent_service import AIAgentService
    from app.modules.llm.services.llm_service_factory import create_llm_service

    llm = await create_llm_service()

    # Build system prompt from the first message in the thread (if it's a system message)
    messages = thread.get_messages_for_llm(max_turns=20)
    system_prompt = ""
    if messages and messages[0]["role"] == "system":
        system_prompt = messages[0]["content"]

    # Skills bound to MCP servers are only exposed when the corresponding MCP is enabled.
    if thread.feature == "global_chat":
        from app.modules.llm.services.skills_service import SKILLS_CATALOG_FOOTER, build_skills_catalog

        skills_catalog = await build_skills_catalog(thread.mcp_config_ids)
        # Strip old skills catalog before appending new one (footer constant shared with skills_service)
        footer_pattern = re.escape(SKILLS_CATALOG_FOOTER)
        system_prompt = re.sub(
            rf"\n?<available_skills>.*?</available_skills>\s*{footer_pattern}",
            "",
            system_prompt,
            flags=re.S,
        ).strip()
        if skills_catalog:
            system_prompt += "\n\n" + skills_catalog

    # Include recent conversation history as context
    prior_turns = []
    for m in messages:
        if m["role"] in ("user", "assistant"):
            prior_turns.append(f"{m['role']}: {_sanitize_prior_turn(m['content'], 300)}")
    # Skip the last user message (it's the current one, passed as task)
    context_summary = ""
    if len(prior_turns) > 1:
        context_summary = "\n\nPrior conversation:\n" + "\n".join(prior_turns[:-1][-8:])

    # Inject memory instruction for interactive threads
    if thread.feature in ("global_chat", "impact_analysis_chat", "impact_group_chat"):
        from app.models.system import SystemConfig as SysConf
        from app.modules.llm.services.prompt_builders import build_memory_instruction

        sys_conf = await SysConf.get_config()
        if getattr(sys_conf, "memory_enabled", True) and "memory_store" not in system_prompt:
            system_prompt += "\n\n" + build_memory_instruction()

    external = await _load_external_mcp_clients(thread.mcp_config_ids)
    elicit_channel = f"llm:{stream_id}" if stream_id else None
    async with _mcp_user_session(
        current_user.id,
        elicitation_channel=elicit_channel,
        extra_clients=external,
        thread_id=str(thread.id),
    ) as all_clients:
        agent = AIAgentService(llm=llm, mcp_clients=all_clients, max_iterations=5)
        return await agent.run(
            task=message,
            system_prompt=system_prompt + context_summary,
            on_tool_call=_make_tool_notifier(stream_id),
        )


async def _stream_or_complete(llm, messages, stream_id: str | None = None, json_mode: bool = False):
    """Complete an LLM request, optionally streaming tokens via WebSocket.

    If ``stream_id`` is provided and ``json_mode`` is False, uses the streaming
    API and broadcasts each token on ``llm:{stream_id}``. Returns the same
    LLMResponse as ``llm.complete()``.
    """
    if not stream_id or json_mode:
        return await llm.complete(messages, json_mode=json_mode)

    from app.core.websocket import ws_manager
    from app.modules.llm.services.llm_service import LLMResponse

    channel = f"llm:{stream_id}"
    chunks: list[str] = []

    async for chunk in llm.stream(messages):
        chunks.append(chunk)
        await ws_manager.broadcast(channel, {"type": "token", "content": chunk})

    content = "".join(chunks)
    await ws_manager.broadcast(channel, {"type": "done", "content": content})

    return LLMResponse(content=content, model=llm.model)


def _agent_result_metadata(result) -> dict | None:
    """Build conversation message metadata from an AgentResult (tool_calls + thinking)."""
    if not result.tool_calls:
        return None
    return {
        "tool_calls": [
            {
                "tool": tc.tool,
                "server": tc.server,
                "arguments": tc.arguments,
                "status": "error" if tc.is_error else "success",
                "result_preview": tc.result,
            }
            for tc in result.tool_calls
        ],
        "thinking_texts": result.thinking_texts,
    }


async def _maybe_trigger_compaction(thread) -> None:
    """Check token budget and schedule background compaction if needed.

    Reads the default LLM config to get model name and context window.
    Fires a background task if token count exceeds 70% of context window.
    """
    if len(thread.messages) < 6:
        return  # Too few messages to bother

    from app.modules.llm.models import LLMConfig
    from app.modules.llm.services.llm_service_factory import _default_model
    from app.modules.llm.services.token_service import count_message_tokens, resolve_context_window
    from app.modules.llm.workers.compaction_worker import _COMPACTION_THRESHOLD

    # NOTE: Uses the default LLM config for token counting. ConversationThread does not
    # currently store which config was used, so we assume the default context window.
    default_cfg = await LLMConfig.find_one(LLMConfig.is_default == True, LLMConfig.enabled == True)  # noqa: E712
    if not default_cfg:
        return
    model = default_cfg.model or _default_model(default_cfg.provider)
    ctx_window = resolve_context_window(default_cfg.context_window_tokens, model)

    all_msgs = [{"role": m.role, "content": m.content} for m in thread.messages]
    token_count = count_message_tokens(all_msgs, model)
    if token_count <= int(ctx_window * _COMPACTION_THRESHOLD):
        return

    from app.core.tasks import create_background_task

    thread_id = str(thread.id)

    async def _run_compaction():
        from app.modules.llm.services.llm_service_factory import create_llm_service
        from app.modules.llm.workers.compaction_worker import compact_thread

        try:
            llm = await create_llm_service()
            await compact_thread(thread_id, llm, ctx_window)
        except Exception as e:
            logger.error("compaction_trigger_failed", thread_id=thread_id, error=str(e))

    create_background_task(_run_compaction(), name=f"compact-{thread_id}")


def _make_tool_notifier(stream_id: str | None):
    """Build a WS-broadcasting callback for real-time tool call events."""
    if not stream_id:
        return None

    async def _notify(event_type: str, data: dict) -> None:
        from app.core.websocket import ws_manager

        await ws_manager.broadcast(f"llm:{stream_id}", {"type": event_type, **data})

    return _notify


# ── Workflow Creation Assistant ───────────────────────────────────────────────


def _usage_dict(response) -> dict:
    """Extract usage stats from an LLM response for API responses."""
    return {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
    }


def _usage_dict_from_agent(result) -> dict:
    """Extract usage stats from an AgentResult for API responses."""
    return {"iterations": result.iterations, "tool_calls": len(result.tool_calls)}


async def _log_llm_usage(user_id, feature: str, llm, response) -> None:
    """Log LLM API usage. Shared helper to avoid repetition."""
    from app.modules.llm.models import LLMUsageLog

    await LLMUsageLog(
        user_id=user_id,
        feature=feature,
        model=response.model,
        provider=llm.provider,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        total_tokens=response.usage.total_tokens,
        duration_ms=response.duration_ms,
    ).insert()


async def _load_or_create_thread(
    thread_id: str | None,
    user_id,
    feature: str,
    prompt_messages: list[dict[str, str]],
    context_ref: str | None = None,
):
    """Load an existing thread (with ownership check) or create a new one."""
    from app.modules.llm.models import ConversationThread

    if thread_id:
        try:
            thread = await ConversationThread.get(PydanticObjectId(thread_id))
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid thread ID") from exc
        if not thread:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation thread not found")
        if thread.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Thread not owned by user")
        return thread

    thread = ConversationThread(user_id=user_id, feature=feature, context_ref=context_ref)
    for m in prompt_messages:
        thread.add_message(m["role"], m["content"])
    await thread.insert()
    return thread


async def _select_relevant_categories(llm, user_request: str) -> list[str]:
    """Pass 1: ask the LLM which API categories are relevant to the request."""
    import json as json_mod

    from app.modules.llm.services.context_service import get_api_categories
    from app.modules.llm.services.llm_service import LLMMessage
    from app.modules.llm.services.prompt_builders import build_category_selection_prompt

    categories = get_api_categories()
    prompt = build_category_selection_prompt(user_request, categories)
    messages = [LLMMessage(role=m["role"], content=m["content"]) for m in prompt]
    response = await llm.complete(messages, json_mode=True)

    try:
        selected = json_mod.loads(response.content)
        if isinstance(selected, list):
            # Validate against actual category names (case-insensitive)
            valid = {c.lower(): c for c in categories}
            return [valid[s.lower()] for s in selected if s.lower() in valid][:8]
    except (json_mod.JSONDecodeError, TypeError):
        pass

    # Fallback: return common categories if parsing fails
    logger.warning("category_selection_parse_failed", raw=response.content[:200])
    return [c for c in categories if any(k in c.lower() for k in ["site", "device", "wlan"])][:5]


@router.post("/llm/workflow/select-categories", response_model=CategorySelectionResponse, tags=["LLM"])
async def select_workflow_categories(
    request: CategorySelectionRequest,
    current_user: User = Depends(require_automation_role),
):
    """Pass 1: select relevant API categories for a workflow description."""
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.services.llm_service_factory import create_llm_service

    llm = await create_llm_service()
    selected = await _select_relevant_categories(llm, request.description)
    return CategorySelectionResponse(categories=selected)


@router.post("/llm/workflow/assist", response_model=WorkflowAssistResponse, tags=["LLM"])
async def workflow_assist(
    request: WorkflowAssistRequest,
    current_user: User = Depends(require_automation_role),
):
    """Pass 2: generate a workflow graph from a natural language description.

    If ``categories`` is provided, skips category selection (pass 1 already done).
    """
    _check_llm_rate_limit(str(current_user.id))
    import json as json_mod

    from app.modules.llm.services.context_service import get_endpoints_for_categories
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_workflow_assist_prompt

    llm = await create_llm_service()

    # Load existing thread for refinement, or create new one
    thread = await _load_or_create_thread(request.thread_id, current_user.id, "workflow_assist", [])
    if not thread.messages:
        # New thread — select categories and build prompt
        selected_categories = request.categories or await _select_relevant_categories(llm, request.description)
        logger.info("workflow_assist_categories", categories=selected_categories)

        api_endpoints = get_endpoints_for_categories(selected_categories)
        prompt_messages = build_workflow_assist_prompt(
            user_request=request.description,
            api_endpoints=api_endpoints,
        )
        for m in prompt_messages:
            thread.add_message(m["role"], m["content"])
        await thread.save()
    else:
        # Follow-up refinement — context is already in the thread
        thread.add_message("user", request.description)
        await thread.save()

    # Generate workflow
    llm_messages = thread.to_llm_messages()
    response = await llm.complete(llm_messages, json_mode=True)

    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "workflow_assist", llm, response)

    # Parse LLM JSON output
    nodes, edges, name, description, explanation = [], [], "", "", ""
    validation_errors: list[str] = []
    try:
        data = json_mod.loads(response.content)
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        name = data.get("name", "")
        description = data.get("description", "")
        explanation = data.get("explanation", "")
    except json_mod.JSONDecodeError:
        validation_errors.append("LLM did not return valid JSON. Try rephrasing your request.")

    # Validate the generated graph
    if nodes and not validation_errors:
        try:
            from app.modules.automation.models.workflow import WorkflowEdge, WorkflowNode
            from app.modules.automation.services.graph_validator import validate_graph

            parsed_nodes = [WorkflowNode(**n) for n in nodes]
            parsed_edges = [WorkflowEdge(**e) for e in edges]
            validate_graph(parsed_nodes, parsed_edges, workflow_type="standard")
        except Exception as e:
            logger.warning("workflow_assist_validation_failed", error=str(e))
            validation_errors.append("Generated workflow graph has structural errors. Try rephrasing.")

    return WorkflowAssistResponse(
        nodes=nodes,
        edges=edges,
        name=name,
        description=description,
        explanation=explanation,
        thread_id=str(thread.id),
        validation_errors=validation_errors,
        usage=_usage_dict(response),
    )


@router.post("/llm/workflow/field-assist", response_model=FieldAssistResponse, tags=["LLM"])
async def workflow_field_assist(
    request: FieldAssistRequest,
    current_user: User = Depends(require_automation_role),
):
    """Help fill a single workflow node field."""
    _check_llm_rate_limit(str(current_user.id))

    from app.modules.llm.services.llm_service import LLMMessage
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_field_assist_prompt

    llm = await create_llm_service()
    prompt_messages = build_field_assist_prompt(
        node_type=request.node_type,
        field_name=request.field_name,
        description=request.description,
        upstream_variables=request.upstream_variables,
    )

    llm_messages = [LLMMessage(role=m["role"], content=m["content"]) for m in prompt_messages]
    response = await llm.complete(llm_messages)

    await _log_llm_usage(current_user.id, "field_assist", llm, response)

    return FieldAssistResponse(
        suggested_value=response.content.strip(),
        usage=_usage_dict(response),
    )


# ── Workflow Debugging ────────────────────────────────────────────────────────


@router.post("/llm/workflow/debug", response_model=DebugExecutionResponse, tags=["LLM"])
async def debug_execution(
    request: DebugExecutionRequest,
    current_user: User = Depends(require_automation_role),
):
    """Analyze a failed workflow execution and suggest fixes."""
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.automation.models.execution import WorkflowExecution
    from app.modules.automation.models.workflow import Workflow
    from app.modules.llm.services.context_service import get_debug_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_debug_prompt

    # Verify the user can access the workflow that owns this execution
    execution = await WorkflowExecution.get(_parse_oid(request.execution_id, "execution ID"))
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    workflow = await Workflow.get(execution.workflow_id)
    if not workflow or not workflow.can_be_accessed_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    llm = await create_llm_service()
    ctx = await get_debug_context(request.execution_id)

    prompt_messages = build_debug_prompt(
        execution_summary=ctx["execution_summary"],
        failed_nodes=ctx["failed_nodes"],
        logs=ctx["logs"],
    )
    thread = await _load_or_create_thread(
        request.thread_id, current_user.id, "workflow_debug", prompt_messages, context_ref=request.execution_id
    )

    llm_messages = thread.to_llm_messages()
    response = await _stream_or_complete(llm, llm_messages, stream_id=request.stream_id)

    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "workflow_debug", llm, response)

    return DebugExecutionResponse(
        analysis=response.content,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )


# ── Webhook Event Summarization ───────────────────────────────────────────────


@router.post("/llm/webhooks/summarize", response_model=WebhookSummaryResponse, tags=["LLM"])
async def summarize_webhook_events(
    request: WebhookSummaryRequest,
    current_user: User = Depends(require_automation_role),
):
    """Summarize recent webhook events using LLM."""
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.services.context_service import get_webhook_summary_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_webhook_summary_prompt

    llm = await create_llm_service()
    events_summary, event_count = await get_webhook_summary_context(hours=request.hours)

    prompt_messages = build_webhook_summary_prompt(events_summary, request.hours, tz_name=current_user.timezone)
    canvas_instr = await _get_canvas_instructions()
    if canvas_instr and prompt_messages and prompt_messages[0]["role"] == "system":
        prompt_messages[0]["content"] += "\n\n" + canvas_instr
    from app.modules.llm.services.skills_service import append_skills_to_messages, build_skills_catalog

    catalog = await build_skills_catalog()
    prompt_messages = append_skills_to_messages(prompt_messages, catalog)
    thread = await _load_or_create_thread(None, current_user.id, "webhook_summary", prompt_messages)

    llm_messages = thread.to_llm_messages()
    response = await _stream_or_complete(llm, llm_messages, stream_id=request.stream_id)

    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "webhook_summary", llm, response)

    return WebhookSummaryResponse(
        summary=response.content,
        event_count=event_count,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )


# ── Dashboard Summarization ─────────────────────────────────────────────────


@router.post("/llm/dashboard/summarize", response_model=WebhookSummaryResponse, tags=["LLM"])
async def summarize_dashboard(
    request: DashboardSummaryRequest,
    current_user: User = Depends(require_automation_role),
):
    """Summarize dashboard state using LLM."""
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.services.context_service import get_dashboard_summary_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_dashboard_summary_prompt

    llm = await create_llm_service()
    context = await get_dashboard_summary_context()

    prompt_messages = build_dashboard_summary_prompt(context, tz_name=current_user.timezone)
    canvas_instr = await _get_canvas_instructions()
    if canvas_instr and prompt_messages and prompt_messages[0]["role"] == "system":
        prompt_messages[0]["content"] += "\n\n" + canvas_instr
    from app.modules.llm.services.skills_service import append_skills_to_messages, build_skills_catalog

    catalog = await build_skills_catalog()
    prompt_messages = append_skills_to_messages(prompt_messages, catalog)
    thread = await _load_or_create_thread(None, current_user.id, "dashboard_summary", prompt_messages)

    llm_messages = thread.to_llm_messages()
    response = await _stream_or_complete(llm, llm_messages, stream_id=request.stream_id)

    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "dashboard_summary", llm, response)

    return WebhookSummaryResponse(
        summary=response.content,
        event_count=0,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )


# ── Audit Log Summarization ─────────────────────────────────────────────────


@router.post("/llm/audit-logs/summarize", response_model=WebhookSummaryResponse, tags=["LLM"])
async def summarize_audit_logs(
    request: AuditLogSummaryRequest,
    current_user: User = Depends(require_admin),
):
    """Summarize audit logs using LLM."""
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.services.context_service import get_audit_log_summary_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_audit_log_summary_prompt

    llm = await create_llm_service()
    context, count = await get_audit_log_summary_context(
        event_type=request.event_type,
        user_id=request.user_id,
        start_date=request.start_date,
        end_date=request.end_date,
    )

    filters = {
        "event_type": request.event_type,
        "user_id": request.user_id,
        "start_date": request.start_date,
        "end_date": request.end_date,
    }
    prompt_messages = build_audit_log_summary_prompt(context, filters, tz_name=current_user.timezone)
    canvas_instr = await _get_canvas_instructions()
    if canvas_instr and prompt_messages and prompt_messages[0]["role"] == "system":
        prompt_messages[0]["content"] += "\n\n" + canvas_instr
    from app.modules.llm.services.skills_service import append_skills_to_messages, build_skills_catalog

    catalog = await build_skills_catalog()
    prompt_messages = append_skills_to_messages(prompt_messages, catalog)
    thread = await _load_or_create_thread(None, current_user.id, "audit_log_summary", prompt_messages)

    llm_messages = thread.to_llm_messages()
    response = await _stream_or_complete(llm, llm_messages, stream_id=request.stream_id)

    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "audit_log_summary", llm, response)

    return WebhookSummaryResponse(
        summary=response.content,
        event_count=count,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )


# ── System Log Summarization ────────────────────────────────────────────────


@router.post("/llm/system-logs/summarize", response_model=WebhookSummaryResponse, tags=["LLM"])
async def summarize_system_logs(
    request: SystemLogSummaryRequest,
    current_user: User = Depends(require_admin),
):
    """Summarize system logs using LLM."""
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.services.context_service import get_system_log_summary_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_system_log_summary_prompt

    llm = await create_llm_service()
    context, count = await get_system_log_summary_context(
        level=request.level,
        logger=request.logger,
    )

    filters = {"level": request.level, "logger": request.logger}
    prompt_messages = build_system_log_summary_prompt(context, filters, tz_name=current_user.timezone)
    canvas_instr = await _get_canvas_instructions()
    if canvas_instr and prompt_messages and prompt_messages[0]["role"] == "system":
        prompt_messages[0]["content"] += "\n\n" + canvas_instr
    from app.modules.llm.services.skills_service import append_skills_to_messages, build_skills_catalog

    catalog = await build_skills_catalog()
    prompt_messages = append_skills_to_messages(prompt_messages, catalog)
    thread = await _load_or_create_thread(None, current_user.id, "system_log_summary", prompt_messages)

    llm_messages = thread.to_llm_messages()
    response = await _stream_or_complete(llm, llm_messages, stream_id=request.stream_id)

    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "system_log_summary", llm, response)

    return WebhookSummaryResponse(
        summary=response.content,
        event_count=count,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )


# ── Backup List Summarization ───────────────────────────────────────────────


@router.post("/llm/backups/summarize", response_model=WebhookSummaryResponse, tags=["LLM"])
async def summarize_backups(
    request: BackupListSummaryRequest,
    current_user: User = Depends(require_backup_role),
):
    """Summarize backup health and change activity using LLM."""
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.services.context_service import get_backup_summary_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_backup_list_summary_prompt

    llm = await create_llm_service()
    context, count = await get_backup_summary_context(
        object_type=request.object_type,
        site_id=request.site_id,
        scope=request.scope,
    )

    filters = {"object_type": request.object_type, "site_id": request.site_id, "scope": request.scope}
    prompt_messages = build_backup_list_summary_prompt(context, filters, tz_name=current_user.timezone)
    canvas_instr = await _get_canvas_instructions()
    if canvas_instr and prompt_messages and prompt_messages[0]["role"] == "system":
        prompt_messages[0]["content"] += "\n\n" + canvas_instr
    from app.modules.llm.services.skills_service import append_skills_to_messages, build_skills_catalog

    catalog = await build_skills_catalog()
    prompt_messages = append_skills_to_messages(prompt_messages, catalog)
    thread = await _load_or_create_thread(None, current_user.id, "backup_summary_list", prompt_messages)

    llm_messages = thread.to_llm_messages()
    response = await _stream_or_complete(llm, llm_messages, stream_id=request.stream_id)

    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "backup_summary_list", llm, response)

    return WebhookSummaryResponse(
        summary=response.content,
        event_count=count,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )


# ── Global Chat ───────────────────────────────────────────────────────────────


@router.post("/llm/chat", response_model=GlobalChatResponse, tags=["LLM"])
async def global_chat(
    request: GlobalChatRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    """Chat about any app data using MCP tools."""
    _check_llm_rate_limit(str(current_user.id))
    from app.modules.llm.services.agent_service import AIAgentService
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import (
        _sanitize_for_prompt,
        build_global_chat_system_prompt,
        build_memory_instruction,
        build_workflow_editor_context,
    )
    from app.modules.llm.services.skills_service import build_skills_catalog

    llm = await create_llm_service()
    # Load or create thread first so we can resolve MCP selection for skills filtering.
    thread = await _load_or_create_thread(request.thread_id, current_user.id, "global_chat", [])

    mcp_ids = request.mcp_config_ids if request.mcp_config_ids is not None else thread.mcp_config_ids
    skills_catalog = await build_skills_catalog(mcp_ids)
    system_prompt = build_global_chat_system_prompt(current_user.roles, tz_name=current_user.timezone)
    canvas_instr = await _get_canvas_instructions()
    if canvas_instr:
        system_prompt += "\n\n" + canvas_instr
    if skills_catalog:
        system_prompt += "\n\n" + skills_catalog

    # Memory instruction (when memory is enabled)
    from app.models.system import SystemConfig as SysConf

    sys_conf = await SysConf.get_config()
    if getattr(sys_conf, "memory_enabled", True):
        system_prompt += "\n\n" + build_memory_instruction()

    safe_ctx = _sanitize_for_prompt(request.page_context, max_len=2000) if request.page_context else None
    if safe_ctx:
        system_prompt += f"\n\nCurrent UI context:\n{safe_ctx}"
        if "Workflow Editor" in safe_ctx:
            system_prompt += build_workflow_editor_context()

    if not thread.messages:
        thread.add_message("system", system_prompt)
        await thread.save()
    elif safe_ctx:
        # Update system prompt with latest page context for existing threads
        if thread.messages and thread.messages[0].role == "system":
            base_prompt = build_global_chat_system_prompt(current_user.roles, tz_name=current_user.timezone)
            if canvas_instr:
                base_prompt += "\n\n" + canvas_instr
            if skills_catalog:
                base_prompt += "\n\n" + skills_catalog
            if getattr(sys_conf, "memory_enabled", True):
                base_prompt += "\n\n" + build_memory_instruction()
            thread.messages[0].content = base_prompt + f"\n\nCurrent UI context:\n{safe_ctx}"

    # Add user message
    thread.add_message("user", request.message)
    await thread.save()

    # Load external MCP clients — validate SSRF before persisting
    external = await _load_external_mcp_clients(mcp_ids)
    if request.mcp_config_ids is not None and request.mcp_config_ids != thread.mcp_config_ids:
        thread.mcp_config_ids = request.mcp_config_ids
        await thread.save()

    # Run agent with local + external MCP servers
    elicit_channel = f"llm:{request.stream_id}" if request.stream_id else None
    async with _mcp_user_session(
        current_user.id,
        elicitation_channel=elicit_channel,
        extra_clients=external,
        thread_id=str(thread.id),
    ) as all_clients:
        agent = AIAgentService(llm=llm, mcp_clients=all_clients, max_iterations=10)

        # Include recent conversation history as context for multi-turn
        history = thread.get_messages_for_llm(max_turns=10)
        context_summary = ""
        if len(history) > 2:
            prior_turns = [f"{m['role']}: {_sanitize_prior_turn(m['content'], 200)}" for m in history[1:-1]]
            context_summary = "\n\nPrior conversation:\n" + "\n".join(prior_turns[-6:])

        result = await agent.run(
            task=request.message,
            system_prompt=system_prompt + context_summary,
            on_tool_call=_make_tool_notifier(request.stream_id),
        )

        reply = result.result
        tool_calls_summary = [{"tool": tc.tool, "arguments": tc.arguments} for tc in result.tool_calls]

    # Store assistant reply (with tool_calls + thinking metadata if MCP tools were used)
    thread.add_message("assistant", reply, metadata=_agent_result_metadata(result))
    await thread.save()

    # Check if compaction is needed (background task, non-blocking)
    await _maybe_trigger_compaction(thread)

    return GlobalChatResponse(
        reply=reply,
        thread_id=str(thread.id),
        tool_calls=tool_calls_summary,
        usage=_usage_dict_from_agent(result),
    )


@router.post("/llm/elicitation/{request_id}/respond", tags=["LLM"])
async def respond_to_elicitation(
    request_id: str,
    request: ElicitationResponseRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    """Respond to a tool elicitation prompt (accept or reject)."""
    from app.modules.mcp_server.helpers import get_elicitation_owner, resolve_elicitation

    # Check existence and ownership before resolving
    owner_id = get_elicitation_owner(request_id)
    if owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Elicitation request not found or already resolved",
        )
    if str(current_user.id) != owner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to respond to this elicitation",
        )

    found = resolve_elicitation(request_id, request.accepted)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Elicitation request not found or already resolved",
        )
    return {"status": "resolved", "accepted": request.accepted}


# ── Conversation Thread History ─────────────────────────────────────────────


def _thread_to_summary(thread) -> ConversationThreadSummary:
    """Build a ConversationThreadSummary from a ConversationThread document or aggregation dict."""
    if isinstance(thread, dict):
        messages = thread.get("messages", [])
        first_user = next((m["content"] for m in messages if m.get("role") == "user"), "")
        return ConversationThreadSummary(
            id=str(thread["_id"]),
            feature=thread.get("feature", ""),
            context_ref=thread.get("context_ref"),
            message_count=len(messages),
            preview=first_user[:100] if first_user else "",
            created_at=thread["created_at"],
            updated_at=thread["updated_at"],
        )
    # Document instance
    first_user = next((m.content for m in thread.messages if m.role == "user"), "")
    return ConversationThreadSummary(
        id=str(thread.id),
        feature=thread.feature,
        context_ref=thread.context_ref,
        message_count=len(thread.messages),
        preview=first_user[:100] if first_user else "",
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


@router.get("/llm/threads", response_model=ConversationThreadListResponse, tags=["LLM"])
async def list_threads(
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    feature: str | None = Query(None),
    current_user: User = Depends(get_current_user_from_token),
):
    """List the current user's conversation threads (newest first)."""
    from app.modules.llm.models import ConversationThread

    match: dict = {"user_id": current_user.id}
    if feature:
        match["feature"] = feature

    pipeline = [
        {"$match": match},
        {"$sort": {"updated_at": -1}},
        {
            "$facet": {
                "total": [{"$count": "n"}],
                "items": [{"$skip": skip}, {"$limit": limit}],
            }
        },
    ]
    results = await ConversationThread.aggregate(pipeline).to_list()
    row = results[0] if results else {}
    total = row.get("total", [{}])[0].get("n", 0) if row.get("total") else 0
    items = row.get("items", [])

    return ConversationThreadListResponse(
        threads=[_thread_to_summary(item) for item in items],
        total=total,
    )


@router.get("/llm/threads/{thread_id}", response_model=ConversationThreadDetail, tags=["LLM"])
async def get_thread(
    thread_id: str,
    current_user: User = Depends(get_current_user_from_token),
):
    """Get a conversation thread with full message history."""
    from app.modules.llm.models import ConversationThread

    thread = await ConversationThread.get(_parse_oid(thread_id, "thread ID"))
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    if thread.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return ConversationThreadDetail(
        id=str(thread.id),
        feature=thread.feature,
        context_ref=thread.context_ref,
        messages=[
            ConversationMessageResponse(role=m.role, content=m.content, metadata=m.metadata, timestamp=m.timestamp)
            for m in thread.messages
        ],
        mcp_config_ids=thread.mcp_config_ids,
        compacted=bool(thread.compaction_summary),
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


@router.delete("/llm/threads/{thread_id}", tags=["LLM"], status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: str,
    current_user: User = Depends(get_current_user_from_token),
):
    """Delete a conversation thread."""
    from app.modules.llm.models import ConversationThread

    thread = await ConversationThread.get(_parse_oid(thread_id, "thread ID"))
    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")
    if thread.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    await thread.delete()


# ── Skills (Agent Skills support) ────────────────────────────────────────────


def _skill_to_response(
    skill, git_repo_url: str | None = None, repo_mcp_config_id: str | None = None
) -> SkillResponse:
    """Build SkillResponse with effective_mcp_config_id resolved from skill or repo."""
    effective_mcp_config_id: str | None = None
    if skill.mcp_config_id:
        effective_mcp_config_id = str(skill.mcp_config_id)
    elif repo_mcp_config_id:
        effective_mcp_config_id = repo_mcp_config_id
    return SkillResponse(
        id=str(skill.id),
        name=skill.name,
        description=skill.description,
        source=skill.source,
        enabled=skill.enabled,
        git_repo_id=str(skill.git_repo_id) if skill.git_repo_id else None,
        git_repo_url=git_repo_url,
        mcp_config_id=str(skill.mcp_config_id) if skill.mcp_config_id else None,
        effective_mcp_config_id=effective_mcp_config_id,
        error=skill.error,
        last_synced_at=skill.last_synced_at,
    )


def _repo_to_response(repo) -> SkillGitRepoResponse:
    return SkillGitRepoResponse(
        id=str(repo.id),
        url=repo.url,
        branch=repo.branch,
        token_set=repo.token_set,
        mcp_config_id=str(repo.mcp_config_id) if repo.mcp_config_id else None,
        local_path=repo.local_path,
        last_refreshed_at=repo.last_refreshed_at,
        error=repo.error,
    )


async def _resolve_mcp_binding(mcp_config_id: str | None) -> PydanticObjectId | None:
    """Validate MCP binding ID and return ObjectId or None when unbound."""
    if not mcp_config_id:
        return None

    from app.modules.llm.models import MCPConfig

    oid = _parse_oid(mcp_config_id, "MCP config ID")
    cfg = await MCPConfig.get(oid)
    if not cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP config not found")
    return oid


@router.get("/llm/skills", tags=["LLM"])
async def list_skills(
    _: User = Depends(require_admin),
):
    """List all skills. Admin only."""
    from app.modules.llm.models import Skill, SkillGitRepo

    skills = await Skill.find_all().to_list()
    # Build a repo URL lookup map to avoid N+1 queries
    repo_ids = {str(s.git_repo_id) for s in skills if s.git_repo_id}
    repos_by_id: dict[str, SkillGitRepo] = {}
    if repo_ids:
        repos = await SkillGitRepo.find({"_id": {"$in": [PydanticObjectId(r) for r in repo_ids]}}).to_list()
        repos_by_id = {str(r.id): r for r in repos}

    responses = []
    for skill in skills:
        repo = repos_by_id.get(str(skill.git_repo_id)) if skill.git_repo_id else None
        repo_mcp_id = str(repo.mcp_config_id) if repo and repo.mcp_config_id else None
        resp = _skill_to_response(skill, repo.url if repo else None, repo_mcp_id)
        responses.append(resp)
    return responses


@router.post("/llm/skills/direct", status_code=status.HTTP_201_CREATED, tags=["LLM"])
async def add_direct_skill(
    request: AddDirectSkillRequest,
    _: User = Depends(require_admin),
):
    """Add a skill by pasting its SKILL.md content. Admin only."""
    import os
    import tempfile
    from datetime import datetime, timezone
    from pathlib import Path

    from app.config import settings
    from app.modules.llm.models import Skill
    from app.modules.llm.services.skills_service import parse_skill_md

    # Parse frontmatter from the submitted content
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tmp:
        tmp.write(request.content)
        tmp_path = tmp.name

    try:
        try:
            name, description, _ = parse_skill_md(Path(tmp_path))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        os.unlink(tmp_path)

    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SKILL.md 'name' field is required")

    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Skill name must be 1-64 chars, lowercase alphanumeric/hyphens/underscores, no path separators",
        )

    # Check for name collision
    existing = await Skill.find_one(Skill.name == name)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A skill named '{name}' already exists")

    # Write to filesystem
    skill_dir = Path(settings.skills_dir) / "direct" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(request.content, encoding="utf-8")

    linked_mcp_oid = await _resolve_mcp_binding(request.mcp_config_id)

    now = datetime.now(timezone.utc)
    skill = Skill(
        name=name,
        description=description,
        source="direct",
        local_path=str(skill_dir),
        enabled=True,
        mcp_config_id=linked_mcp_oid,
        error=None,
        last_synced_at=now,
    )
    await skill.insert()
    return _skill_to_response(skill)


# ── Skill Git Repos ───────────────────────────────────────────────────────────
# NOTE: These routes use the literal path segment "repos" and MUST be registered
# BEFORE the /{skill_id}/ routes below, otherwise FastAPI would match "repos" as
# a skill_id variable and these endpoints would be unreachable.


@router.get("/llm/skills/repos", tags=["LLM"])
async def list_skill_repos(
    _: User = Depends(require_admin),
):
    """List all git repo skills sources. Admin only."""
    from app.modules.llm.models import SkillGitRepo

    repos = await SkillGitRepo.find_all().to_list()
    return [_repo_to_response(r) for r in repos]


@router.get("/llm/skills/repos/{repo_id}", tags=["LLM"])
async def get_skill_repo(
    repo_id: str,
    _: User = Depends(require_admin),
):
    """Get a single git repo record (used for polling status). Admin only."""
    from app.modules.llm.models import SkillGitRepo

    oid = _parse_oid(repo_id, "repo ID")
    repo = await SkillGitRepo.get(oid)
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")
    return _repo_to_response(repo)


async def _clone_and_scan(repo_id: str) -> None:
    """Background task: clone a git repo and scan for skills."""
    from datetime import datetime, timezone
    from pathlib import Path

    from app.core.security import decrypt_sensitive_data
    from app.modules.llm.models import SkillGitRepo
    from app.modules.llm.services.skills_service import clone_repo, sync_skills_from_repo

    repo = await SkillGitRepo.get(PydanticObjectId(repo_id))
    if not repo:
        return

    token = decrypt_sensitive_data(repo.token) if repo.token else None

    try:
        await clone_repo(repo.url, token, repo.branch, Path(repo.local_path))
        added, updated = await sync_skills_from_repo(repo_id, Path(repo.local_path))
        repo.last_refreshed_at = datetime.now(timezone.utc)
        repo.error = None
        repo.update_timestamp()
        await repo.save()
        logger.info("skill_repo_cloned", repo_id=repo_id, added=added, updated=updated)
    except Exception as exc:
        repo.error = str(exc)[:500]
        repo.update_timestamp()
        await repo.save()
        logger.error("skill_repo_clone_failed", repo_id=repo_id, error=str(exc))


async def _pull_and_scan(repo_id: str) -> None:
    """Background task: pull a git repo and re-scan for skills."""
    from datetime import datetime, timezone
    from pathlib import Path

    from app.core.security import decrypt_sensitive_data
    from app.modules.llm.models import SkillGitRepo
    from app.modules.llm.services.skills_service import pull_repo, sync_skills_from_repo

    repo = await SkillGitRepo.get(PydanticObjectId(repo_id))
    if not repo:
        return
    if not repo.local_path:
        logger.error("skill_repo_pull_skipped_no_path", repo_id=repo_id)
        return

    token = decrypt_sensitive_data(repo.token) if repo.token else None

    try:
        await pull_repo(Path(repo.local_path), repo.url, token)
        added, updated = await sync_skills_from_repo(repo_id, Path(repo.local_path))
        repo.last_refreshed_at = datetime.now(timezone.utc)
        repo.error = None
        repo.update_timestamp()
        await repo.save()
        logger.info("skill_repo_pulled", repo_id=repo_id, added=added, updated=updated)
    except Exception as exc:
        repo.error = str(exc)[:500]
        repo.update_timestamp()
        await repo.save()
        logger.error("skill_repo_pull_failed", repo_id=repo_id, error=str(exc))


@router.post("/llm/skills/repos", status_code=status.HTTP_201_CREATED, tags=["LLM"])
async def add_skill_repo(
    request: AddGitRepoRequest,
    _: User = Depends(require_admin),
):
    """Add a git repo as a skills source. Clone + scan runs in the background. Admin only."""
    from pathlib import Path

    from app.config import settings
    from app.core.security import encrypt_sensitive_data
    from app.core.tasks import create_background_task
    from app.modules.llm.models import SkillGitRepo
    from app.utils.url_safety import validate_outbound_url

    try:
        validate_outbound_url(request.url)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid URL: {exc}") from exc

    encrypted_token = encrypt_sensitive_data(request.token) if request.token else None
    linked_mcp_oid = await _resolve_mcp_binding(request.mcp_config_id)

    repo = SkillGitRepo(
        url=request.url,
        branch=request.branch,
        token=encrypted_token,
        mcp_config_id=linked_mcp_oid,
        local_path="",  # set after insert (need the ID for the path)
    )
    await repo.insert()

    local_path = str(Path(settings.skills_dir) / "repos" / str(repo.id))
    repo.local_path = local_path
    repo.update_timestamp()
    await repo.save()

    create_background_task(_clone_and_scan(str(repo.id)), name=f"clone_skill_repo_{repo.id}")
    return _repo_to_response(repo)


@router.patch("/llm/skills/repos/{repo_id}/mcp-server", tags=["LLM"])
async def set_skill_repo_mcp_server(
    repo_id: str,
    request: SkillMcpServerUpdateRequest,
    _: User = Depends(require_admin),
):
    """Bind or unbind a git skills repo to a specific MCP server. Admin only."""
    from app.modules.llm.models import SkillGitRepo

    oid = _parse_oid(repo_id, "repo ID")
    repo = await SkillGitRepo.get(oid)
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")

    linked_mcp_oid = await _resolve_mcp_binding(request.mcp_config_id)
    repo.mcp_config_id = linked_mcp_oid
    repo.update_timestamp()
    await repo.save()
    return _repo_to_response(repo)


@router.post("/llm/skills/repos/{repo_id}/refresh", status_code=status.HTTP_202_ACCEPTED, tags=["LLM"])
async def refresh_skill_repo(
    repo_id: str,
    _: User = Depends(require_admin),
):
    """Pull latest changes and re-scan for skills. Runs in the background. Admin only."""
    from app.core.tasks import create_background_task
    from app.modules.llm.models import SkillGitRepo

    oid = _parse_oid(repo_id, "repo ID")
    repo = await SkillGitRepo.get(oid)
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")

    create_background_task(_pull_and_scan(repo_id), name=f"pull_skill_repo_{repo_id}")
    return {"status": "refreshing"}


@router.delete("/llm/skills/repos/{repo_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["LLM"])
async def delete_skill_repo(
    repo_id: str,
    _: User = Depends(require_admin),
):
    """Delete a git repo, all its skills, and the cloned directory. Admin only."""
    from pathlib import Path

    from app.modules.llm.models import Skill, SkillGitRepo
    from app.modules.llm.services.skills_service import remove_dir

    oid = _parse_oid(repo_id, "repo ID")
    repo = await SkillGitRepo.get(oid)
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")

    # Delete all skills from this repo
    await Skill.find(Skill.git_repo_id == oid).delete()

    # Remove cloned directory
    remove_dir(Path(repo.local_path))

    await repo.delete()


# ── Individual Skill Management ───────────────────────────────────────────────


@router.patch("/llm/skills/{skill_id}/mcp-server", tags=["LLM"])
async def set_skill_mcp_server(
    skill_id: str,
    request: SkillMcpServerUpdateRequest,
    _: User = Depends(require_admin),
):
    """Bind or unbind a direct skill to a specific MCP server. Admin only."""
    from app.modules.llm.models import Skill

    oid = _parse_oid(skill_id, "skill ID")
    skill = await Skill.get(oid)
    if not skill:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    if skill.source != "direct":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only direct-imported skills can be configured at skill level. Use repo MCP binding for git skills.",
        )

    linked_mcp_oid = await _resolve_mcp_binding(request.mcp_config_id)
    skill.mcp_config_id = linked_mcp_oid
    skill.update_timestamp()
    await skill.save()
    return _skill_to_response(skill)


@router.patch("/llm/skills/{skill_id}/toggle", tags=["LLM"])
async def toggle_skill(
    skill_id: str,
    _: User = Depends(require_admin),
):
    """Enable or disable a skill. Admin only."""
    from app.modules.llm.models import Skill, SkillGitRepo

    oid = _parse_oid(skill_id, "skill ID")
    skill = await Skill.get(oid)
    if not skill:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")

    skill.enabled = not skill.enabled
    skill.update_timestamp()
    await skill.save()

    # Resolve repo for git-sourced skills to get effective MCP binding
    repo = None
    if skill.git_repo_id:
        repo = await SkillGitRepo.get(skill.git_repo_id)
    repo_mcp_id = str(repo.mcp_config_id) if repo and repo.mcp_config_id else None
    return _skill_to_response(skill, repo.url if repo else None, repo_mcp_id)


@router.delete("/llm/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["LLM"])
async def delete_skill(
    skill_id: str,
    _: User = Depends(require_admin),
):
    """Delete a direct-source skill (and its directory). Git-sourced skills cannot be deleted individually. Admin only."""
    from pathlib import Path

    from app.modules.llm.models import Skill
    from app.modules.llm.services.skills_service import remove_dir

    oid = _parse_oid(skill_id, "skill ID")
    skill = await Skill.get(oid)
    if not skill:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    if skill.source == "git":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Git-sourced skills cannot be deleted individually. Disable the skill or delete the repo.",
        )

    remove_dir(Path(skill.local_path))
    await skill.delete()


# ── User Memory ─────────────────────────────────────────────────────────────


def _memory_to_response(entry) -> MemoryEntryResponse:
    """Build a MemoryEntryResponse from a MemoryEntry document."""
    return MemoryEntryResponse(
        id=str(entry.id),
        key=entry.key,
        value=entry.value,
        category=entry.category,
        source_thread_id=entry.source_thread_id,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


@router.get("/llm/memories", response_model=MemoryListResponse, tags=["LLM"])
async def list_memories(
    category: str | None = Query(None, description="Filter by category"),
    search: str | None = Query(None, description="Text search across key and value"),
    current_user: User = Depends(get_current_user_from_token),
):
    """List the current user's memory entries."""
    from app.modules.llm.models import MemoryEntry

    filters: dict = {"user_id": current_user.id}

    if category:
        filters["category"] = category

    if search:
        filters["$text"] = {"$search": search}

    entries = await MemoryEntry.find(filters).sort("-updated_at").to_list()

    return MemoryListResponse(
        entries=[_memory_to_response(e) for e in entries],
        total=len(entries),
    )


@router.get("/llm/memories/{memory_id}", response_model=MemoryEntryResponse, tags=["LLM"])
async def get_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user_from_token),
):
    """Get a single memory entry. Verifies ownership."""
    from app.modules.llm.models import MemoryEntry

    entry = await MemoryEntry.get(_parse_oid(memory_id, "memory ID"))
    if not entry or entry.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    return _memory_to_response(entry)


@router.put("/llm/memories/{memory_id}", response_model=MemoryEntryResponse, tags=["LLM"])
async def update_memory(
    memory_id: str,
    request: MemoryUpdateRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    """Update a memory entry's value and/or category."""
    from datetime import datetime, timezone

    from app.modules.llm.memory_constants import VALID_MEMORY_CATEGORIES
    from app.modules.llm.models import MemoryEntry

    entry = await MemoryEntry.get(_parse_oid(memory_id, "memory ID"))
    if not entry or entry.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    if request.value is not None:
        from app.models.system import SystemConfig

        config = await SystemConfig.get_config()
        max_len = config.memory_entry_max_length
        if len(request.value) > max_len:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Value must be {max_len} characters or fewer",
            )
        entry.value = request.value

    if request.category is not None:
        if request.category not in VALID_MEMORY_CATEGORIES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid category. Must be one of: {', '.join(sorted(VALID_MEMORY_CATEGORIES))}",
            )
        entry.category = request.category

    entry.updated_at = datetime.now(timezone.utc)
    await entry.save()

    return _memory_to_response(entry)


@router.delete("/llm/memories/{memory_id}", tags=["LLM"])
async def delete_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user_from_token),
):
    """Delete a single memory entry. Verifies ownership."""
    from app.modules.llm.models import MemoryEntry

    entry = await MemoryEntry.get(_parse_oid(memory_id, "memory ID"))
    if not entry or entry.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    key = entry.key
    await entry.delete()
    return {"status": "deleted", "key": key}


@router.delete("/llm/memories", tags=["LLM"])
async def delete_all_memories(
    confirm: bool = Query(False, description="Must be true to confirm deletion"),
    current_user: User = Depends(get_current_user_from_token),
):
    """Delete all memory entries for the current user. Requires confirm=true."""
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must pass confirm=true to delete all memories",
        )

    from app.modules.llm.models import MemoryEntry

    result = await MemoryEntry.find(MemoryEntry.user_id == current_user.id).delete()
    count = result.deleted_count if result else 0
    return {"status": "deleted", "count": count}
