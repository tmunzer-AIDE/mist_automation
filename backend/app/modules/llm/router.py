"""
LLM API endpoints.
"""

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user_from_token, require_backup_role
from app.models.user import User
from app.modules.llm.schemas import ChatResponse, FollowUpRequest, SummarizeDiffRequest, SummaryResponse
from app.modules.llm.services.llm_service_factory import is_llm_available

router = APIRouter()
logger = structlog.get_logger(__name__)


# ── Status & Test ─────────────────────────────────────────────────────────────


@router.get("/llm/status", tags=["LLM"])
async def get_llm_status(_current_user: User = Depends(get_current_user_from_token)):
    """Check if LLM features are available."""
    from app.models.system import SystemConfig

    available = await is_llm_available()
    if not available:
        return {"enabled": False, "provider": None, "model": None}

    config = await SystemConfig.get_config()
    return {
        "enabled": True,
        "provider": config.llm_provider,
        "model": config.llm_model,
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


# ── Backup Summarization ─────────────────────────────────────────────────────


@router.post("/llm/backup/summarize", response_model=SummaryResponse, tags=["LLM"])
async def summarize_backup_change(
    request: SummarizeDiffRequest,
    current_user: User = Depends(require_backup_role),
):
    """Generate an LLM summary of changes between two backup object versions."""
    from app.modules.llm.models import ConversationThread, LLMUsageLog
    from app.modules.llm.services.context_service import get_backup_diff_context
    from app.modules.llm.services.llm_service import LLMMessage
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
    )

    # Load or create conversation thread
    thread = None
    if request.thread_id:
        thread = await ConversationThread.get(PydanticObjectId(request.thread_id))
        if thread and thread.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Thread not owned by user")

    if not thread:
        thread = ConversationThread(
            user_id=current_user.id,
            feature="backup_summary",
            context_ref=request.version_id_2,
        )
        # Add system + user messages
        for m in prompt_messages:
            thread.add_message(m["role"], m["content"])
        await thread.insert()
    else:
        # Re-use thread — the original context is already in the thread
        pass

    # Build messages for LLM: full thread history
    llm_messages = [LLMMessage(role=m["role"], content=m["content"]) for m in thread.get_messages_for_llm()]

    response = await llm.complete(llm_messages)

    # Store assistant reply
    thread.add_message("assistant", response.content)
    await thread.save()

    # Log usage
    await LLMUsageLog(
        user_id=current_user.id,
        feature="backup_summary",
        model=response.model,
        provider=llm.provider,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        total_tokens=response.usage.total_tokens,
        duration_ms=response.duration_ms,
    ).insert()

    return SummaryResponse(
        summary=response.content,
        thread_id=str(thread.id),
        usage={
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
        },
    )


# ── Conversation Follow-Up ───────────────────────────────────────────────────


@router.post("/llm/chat/{thread_id}", response_model=ChatResponse, tags=["LLM"])
async def continue_conversation(
    thread_id: str,
    request: FollowUpRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    """Continue an existing LLM conversation thread."""
    from app.modules.llm.models import ConversationThread, LLMUsageLog
    from app.modules.llm.services.llm_service import LLMMessage
    from app.modules.llm.services.llm_service_factory import create_llm_service

    try:
        thread = await ConversationThread.get(PydanticObjectId(thread_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid thread ID") from exc

    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation thread not found")
    if thread.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Thread not owned by user")

    # Add user message
    thread.add_message("user", request.message)

    # Call LLM with full conversation history
    llm = await create_llm_service()
    llm_messages = [LLMMessage(role=m["role"], content=m["content"]) for m in thread.get_messages_for_llm()]
    response = await llm.complete(llm_messages)

    # Store assistant reply
    thread.add_message("assistant", response.content)
    await thread.save()

    # Log usage
    await LLMUsageLog(
        user_id=current_user.id,
        feature=thread.feature,
        model=response.model,
        provider=llm.provider,
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        total_tokens=response.usage.total_tokens,
        duration_ms=response.duration_ms,
    ).insert()

    return ChatResponse(
        reply=response.content,
        thread_id=str(thread.id),
        usage={
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
        },
    )
