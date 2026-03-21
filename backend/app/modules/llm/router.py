"""
LLM API endpoints.
"""

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user_from_token, require_automation_role, require_backup_role
from app.models.user import User
from app.modules.llm.schemas import (
    CategorySelectionRequest,
    CategorySelectionResponse,
    ChatResponse,
    DebugExecutionRequest,
    DebugExecutionResponse,
    FieldAssistRequest,
    FieldAssistResponse,
    FollowUpRequest,
    SummarizeDiffRequest,
    SummaryResponse,
    WebhookSummaryRequest,
    WebhookSummaryResponse,
    WorkflowAssistRequest,
    WorkflowAssistResponse,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


# ── Status & Test ─────────────────────────────────────────────────────────────


@router.get("/llm/status", tags=["LLM"])
async def get_llm_status(_current_user: User = Depends(get_current_user_from_token)):
    """Check if LLM features are available."""
    from app.models.system import SystemConfig

    config = await SystemConfig.get_config()
    if not (config.llm_enabled and config.llm_provider and config.llm_api_key):
        return {"enabled": False, "provider": None, "model": None}

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
    )

    thread = await _load_or_create_thread(
        request.thread_id, current_user.id, "backup_summary", prompt_messages, context_ref=request.version_id_2
    )

    # Build messages for LLM: full thread history
    llm_messages = thread.to_llm_messages()

    response = await llm.complete(llm_messages)

    # Store assistant reply
    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "backup_summary", llm, response)

    return SummaryResponse(
        summary=response.content,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )


# ── Conversation Follow-Up ───────────────────────────────────────────────────


@router.post("/llm/chat/{thread_id}", response_model=ChatResponse, tags=["LLM"])
async def continue_conversation(
    thread_id: str,
    request: FollowUpRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    """Continue an existing LLM conversation thread."""
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

    # Add user message and persist before LLM call (so it's not lost on failure)
    thread.add_message("user", request.message)
    await thread.save()

    # Call LLM with full conversation history
    llm = await create_llm_service()
    llm_messages = thread.to_llm_messages()
    response = await llm.complete(llm_messages)

    # Store assistant reply
    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, thread.feature, llm, response)

    return ChatResponse(
        reply=response.content,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )


# ── Workflow Creation Assistant ───────────────────────────────────────────────


def _usage_dict(response) -> dict:
    """Extract usage stats from an LLM response for API responses."""
    return {
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
    }


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


@router.post(
    "/llm/workflow/select-categories", response_model=CategorySelectionResponse, tags=["LLM"]
)
async def select_workflow_categories(
    request: CategorySelectionRequest,
    current_user: User = Depends(require_automation_role),
):
    """Pass 1: select relevant API categories for a workflow description."""
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
    from app.modules.automation.models.execution import WorkflowExecution
    from app.modules.automation.models.workflow import Workflow
    from app.modules.llm.services.context_service import get_debug_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_debug_prompt

    # Verify the user can access the workflow that owns this execution
    execution = await WorkflowExecution.get(PydanticObjectId(request.execution_id))
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
    response = await llm.complete(llm_messages)

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
    from app.modules.llm.services.context_service import get_webhook_summary_context
    from app.modules.llm.services.llm_service_factory import create_llm_service
    from app.modules.llm.services.prompt_builders import build_webhook_summary_prompt

    llm = await create_llm_service()
    events_summary, event_count = await get_webhook_summary_context(hours=request.hours)

    prompt_messages = build_webhook_summary_prompt(events_summary, request.hours)
    thread = await _load_or_create_thread(None, current_user.id, "webhook_summary", prompt_messages)

    llm_messages = thread.to_llm_messages()
    response = await llm.complete(llm_messages)

    thread.add_message("assistant", response.content)
    await thread.save()

    await _log_llm_usage(current_user.id, "webhook_summary", llm, response)

    return WebhookSummaryResponse(
        summary=response.content,
        event_count=event_count,
        thread_id=str(thread.id),
        usage=_usage_dict(response),
    )
