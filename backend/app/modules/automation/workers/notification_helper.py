"""
Shared helper for dispatching workflow failure notifications.

Used by both webhook_worker and cron_worker after execution completes
with a terminal failure status.
"""

from datetime import datetime, timezone

import structlog

from app.modules.automation.models.execution import ExecutionStatus, WorkflowExecution
from app.modules.automation.models.workflow import NotificationChannel, Workflow
from app.services.notification_service import NotificationService

logger = structlog.get_logger(__name__)


async def notify_workflow_failure(workflow: Workflow, execution: WorkflowExecution) -> None:
    """Dispatch a failure notification for a workflow execution.

    This function never raises — all exceptions are logged and swallowed
    so that notification failures do not affect execution state.
    """
    try:
        config = workflow.failure_notification
        if not config or not config.enabled:
            return

        # Build notification context
        context = _build_context(workflow, execution)
        message = _build_message(context)

        service = NotificationService()
        try:
            if config.channel == NotificationChannel.SLACK:
                await service.send_slack_notification(
                    webhook_url=config.slack_webhook_url,
                    message=message,
                    color="danger",
                    fields=[
                        {"title": "Workflow", "value": context["workflow_name"], "short": True},
                        {"title": "Status", "value": context["status"], "short": True},
                        {"title": "Duration", "value": f"{context['duration_ms']}ms", "short": True},
                        {"title": "Nodes Failed", "value": str(context["nodes_failed"]), "short": True},
                    ],
                )

            elif config.channel == NotificationChannel.EMAIL:
                if config.email_recipients:
                    body = f"<h3>Workflow Failed: {context['workflow_name']}</h3>"
                    body += f"<p><b>Status:</b> {context['status']}</p>"
                    body += f"<p><b>Duration:</b> {context['duration_ms']}ms</p>"
                    if context["error"] and config.include_error_details:
                        body += f"<p><b>Error:</b> {context['error']}</p>"
                    await service.send_email(
                        to=config.email_recipients,
                        subject=f"Workflow Failed: {context['workflow_name']}",
                        body=body,
                        html=True,
                    )

            elif config.channel == NotificationChannel.PAGERDUTY:
                await service.send_pagerduty_alert(
                    integration_key=config.pagerduty_integration_key,
                    summary=f"Workflow '{context['workflow_name']}' failed",
                    severity="error",
                    custom_details={
                        "workflow_id": context["workflow_id"],
                        "execution_id": context["execution_id"],
                        "status": context["status"],
                        "error": context["error"] if config.include_error_details else None,
                        "nodes_failed": context["nodes_failed"],
                    },
                )

            elif config.channel == NotificationChannel.SERVICENOW:
                from app.core.security import decrypt_sensitive_data
                from app.models.system import SystemConfig

                sys_config = await SystemConfig.get_config()
                await service.send_servicenow_notification(
                    instance_url=sys_config.servicenow_instance_url,
                    username=sys_config.servicenow_username,
                    password=decrypt_sensitive_data(sys_config.servicenow_password) if sys_config.servicenow_password else None,
                    short_description=f"Workflow '{context['workflow_name']}' failed",
                    description=message,
                    urgency=2,
                )

            logger.info(
                "failure_notification_sent",
                workflow_id=context["workflow_id"],
                execution_id=context["execution_id"],
                channel=config.channel.value,
            )
        finally:
            try:
                await service.close()
            except Exception:
                logger.debug("notification_service_close_failed", exc_info=True)

    except Exception:
        logger.warning(
            "failure_notification_failed",
            workflow_id=str(workflow.id),
            execution_id=str(execution.id),
            exc_info=True,
        )


def _build_context(workflow: Workflow, execution: WorkflowExecution) -> dict:
    """Build a context dict from workflow and execution for notification templates."""
    return {
        "workflow_name": workflow.name,
        "workflow_id": str(workflow.id),
        "execution_id": str(execution.id),
        "status": execution.status.value if isinstance(execution.status, ExecutionStatus) else str(execution.status),
        "error": execution.error,
        "duration_ms": execution.duration_ms or 0,
        "nodes_executed": execution.nodes_executed,
        "nodes_succeeded": execution.nodes_succeeded,
        "nodes_failed": execution.nodes_failed,
        "started_at": execution.started_at.isoformat() if execution.started_at else "",
        "trigger_type": execution.trigger_type,
    }


def _build_message(context: dict) -> str:
    """Build a plain-text notification message."""
    lines = [
        f"Workflow *{context['workflow_name']}* failed.",
        f"Status: {context['status']} | Duration: {context['duration_ms']}ms",
        f"Nodes: {context['nodes_executed']} executed, {context['nodes_failed']} failed",
    ]
    if context["error"]:
        lines.append(f"Error: {context['error']}")
    return "\n".join(lines)
