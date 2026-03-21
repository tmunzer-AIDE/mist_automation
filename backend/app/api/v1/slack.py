"""
Slack interactive callback endpoint.

Handles interactive payloads (button clicks) from Slack messages and
resumes paused workflow executions (wait_for_callback nodes).
"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs

import structlog
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Request

from app.config import settings
from app.core.tasks import create_background_task
from app.models.system import SystemConfig

router = APIRouter()
logger = structlog.get_logger(__name__)


def _verify_slack_signature(body: bytes, signature: str, timestamp: str, signing_secret: str) -> bool:
    """Verify the Slack request signature using HMAC-SHA256.

    Slack signs requests with ``v0=hmac-sha256(signing_secret, "v0:{timestamp}:{body}")``.
    """
    if not signature or not timestamp or not signing_secret:
        return False

    # Reject requests older than 5 minutes to prevent replay attacks
    try:
        if abs(time.time() - int(timestamp)) > 60 * 5:
            return False
    except (ValueError, TypeError):
        return False

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _validate_object_id(value: str) -> bool:
    """Check whether *value* is a valid MongoDB ObjectId hex string."""
    try:
        ObjectId(value)
        return True
    except (InvalidId, TypeError):
        return False


async def _resume_paused_execution(execution, workflow, callback_data: dict) -> None:
    """Resume a paused workflow execution as a background coroutine."""
    from app.modules.automation.services.executor_service import resume_from_callback

    await resume_from_callback(execution, workflow, callback_data)


@router.post("/webhooks/slack/interactive", tags=["Slack"])
async def handle_slack_interactive(request: Request):
    """
    Handle Slack interactive payloads (button clicks).

    Slack sends ``application/x-www-form-urlencoded`` with a ``payload``
    field containing the JSON body.  Smee-forwarded requests arrive as
    ``application/json``.  Returns 200 in all cases (Slack retries on
    non-200 responses).
    """
    body = await request.body()
    content_type = request.headers.get("content-type", "")

    # ── Parse payload ────────────────────────────────────────────────────
    try:
        if "application/x-www-form-urlencoded" in content_type:
            form = parse_qs(body.decode("utf-8"))
            payload_str = form.get("payload", [""])[0]
            payload = json.loads(payload_str)
        else:
            # JSON body (Smee-forwarded or direct JSON)
            payload = json.loads(body)
    except (json.JSONDecodeError, KeyError, IndexError):
        logger.warning("slack_interactive_invalid_payload")
        return {"ok": True, "error": "Invalid payload format"}

    # ── Signature verification ───────────────────────────────────────────
    smee_forwarded = (
        settings.debug
        and request.headers.get("x-forwarded-by") == "smee"
        and request.client
        and request.client.host in ("127.0.0.1", "::1")
    )

    if not smee_forwarded:
        config = await SystemConfig.get_config()
        if config.slack_signing_secret:
            from app.core.security import decrypt_sensitive_data

            signing_secret = decrypt_sensitive_data(config.slack_signing_secret)
            slack_signature = request.headers.get("x-slack-signature", "")
            slack_timestamp = request.headers.get("x-slack-request-timestamp", "")

            if not _verify_slack_signature(body, slack_signature, slack_timestamp, signing_secret):
                logger.warning("slack_interactive_signature_invalid")
                return {"ok": True, "error": "Invalid signature"}
        else:
            logger.warning("slack_interactive_no_signing_secret")

    # ── Extract action ───────────────────────────────────────────────────
    actions = payload.get("actions", [])
    if not actions:
        logger.info("slack_interactive_no_actions")
        return {"ok": True}

    action = actions[0]
    action_id = action.get("action_id", "")
    value_raw = action.get("value", "{}")

    try:
        value = json.loads(value_raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("slack_interactive_invalid_action_value", value=str(value_raw)[:200])
        return {"ok": True, "error": "Invalid action value"}

    execution_id = value.get("execution_id", "")
    node_id = value.get("node_id", "")
    workflow_id = value.get("workflow_id", "")

    # Validate ObjectId format
    if not _validate_object_id(execution_id):
        logger.warning("slack_interactive_invalid_execution_id", execution_id=execution_id)
        return {"ok": True, "error": "Invalid execution ID"}
    if not _validate_object_id(workflow_id):
        logger.warning("slack_interactive_invalid_workflow_id", workflow_id=workflow_id)
        return {"ok": True, "error": "Invalid workflow ID"}

    logger.info(
        "slack_interactive_received",
        action_id=action_id,
        execution_id=execution_id,
        node_id=node_id,
        workflow_id=workflow_id,
        user=payload.get("user", {}).get("username", "unknown"),
    )

    # ── Load execution and resume paused workflow ──────────────────────────
    from beanie import PydanticObjectId

    from app.modules.automation.models.execution import ExecutionStatus, WorkflowExecution
    from app.modules.automation.models.workflow import Workflow

    try:
        execution = await WorkflowExecution.get(PydanticObjectId(execution_id))
    except Exception:
        logger.warning("slack_interactive_execution_lookup_failed", execution_id=execution_id)
        return {"ok": True, "error": "Execution not found"}

    if not execution:
        logger.warning("slack_interactive_execution_not_found", execution_id=execution_id)
        return {"ok": True, "error": "Execution not found"}

    # Verify execution is in WAITING state at the expected node
    if execution.status != ExecutionStatus.WAITING or execution.paused_node_id != node_id:
        logger.warning(
            "slack_interactive_not_waiting",
            execution_id=execution_id,
            status=execution.status,
            paused_node_id=execution.paused_node_id,
            expected_node_id=node_id,
        )
        return {"ok": True, "error": "Execution is not waiting for a callback at this node"}

    # Load the workflow
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception:
        logger.warning("slack_interactive_workflow_lookup_failed", workflow_id=workflow_id)
        return {"ok": True, "error": "Workflow not found"}

    if not workflow:
        logger.warning("slack_interactive_workflow_not_found", workflow_id=workflow_id)
        return {"ok": True, "error": "Workflow not found"}

    # ── Resume paused execution ──────────────────────────────────────────
    callback_data = {
        "action_id": action_id,
        "user": payload.get("user", {}),
        "channel": payload.get("channel", {}),
        "response_url": payload.get("response_url"),
    }

    create_background_task(
        _resume_paused_execution(execution, workflow, callback_data),
        name=f"slack-resume-{execution_id}-{action_id}",
    )

    logger.info(
        "slack_interactive_resume_triggered",
        execution_id=execution_id,
        workflow_id=workflow_id,
        node_id=node_id,
        action_id=action_id,
    )

    return {"ok": True}
