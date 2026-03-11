"""
Notification service for external integrations (Slack, ServiceNow, PagerDuty).
"""

from typing import Any, Optional
from datetime import datetime, timezone
import structlog
import httpx
from jinja2.sandbox import SandboxedEnvironment

from app.core.exceptions import NotificationError, ConfigurationError
from app.config import settings

logger = structlog.get_logger(__name__)


class NotificationService:
    """Service for sending notifications to external systems."""

    def __init__(self):
        """Initialize notification service."""
        self._http_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create an httpx client with the right TLS verify option."""
        if self._http_client is None:
            verify = await self._resolve_verify()
            self._http_client = httpx.AsyncClient(timeout=30.0, verify=verify)
        return self._http_client

    @staticmethod
    async def _resolve_verify() -> str | bool:
        """Try TLS options in order: CA_CERT_PATH → default → disabled.

        Same fallback strategy as SmeeClient for ZScaler/TLS-intercepting proxies.
        """
        import os

        from app.core.smee_service import _build_verify_options

        options = _build_verify_options()
        for option in options:
            try:
                async with httpx.AsyncClient(verify=option) as client:
                    await client.head("https://slack.com", timeout=10)
                return option
            except Exception:
                continue

        return False

    async def send_slack_notification(
        self,
        webhook_url: Optional[str],
        message: str,
        channel: Optional[str] = None,
        username: str = "Mist Automation",
        icon_emoji: str = ":robot_face:",
        color: str = "good",
        fields: Optional[list[dict[str, Any]]] = None,
        blocks: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """
        Send notification to Slack.

        Args:
            webhook_url: Slack webhook URL
            message: Message text (also used as fallback when blocks are provided)
            channel: Optional channel override
            username: Bot username
            icon_emoji: Bot icon emoji
            color: Message color (good, warning, danger, or hex)
            fields: Optional list of attachment fields
            blocks: Optional Block Kit blocks (rich_text tables, etc.)

        Returns:
            Response data

        Raises:
            NotificationError: If notification fails
        """
        url = webhook_url or settings.slack_webhook_url
        if not url:
            raise ConfigurationError("Slack webhook URL not configured")

        try:
            if blocks:
                # Block Kit payload — blocks take precedence, message is fallback
                payload: dict[str, Any] = {
                    "username": username,
                    "icon_emoji": icon_emoji,
                    "text": message,
                    "blocks": blocks,
                }
            else:
                # Legacy attachments payload
                payload = {
                    "username": username,
                    "icon_emoji": icon_emoji,
                    "attachments": [
                        {
                            "color": color,
                            "text": message,
                            "footer": "Mist Automation",
                            "ts": int(datetime.now(timezone.utc).timestamp()),
                        }
                    ],
                }
                # Add fields if provided
                if fields:
                    payload["attachments"][0]["fields"] = fields

            # Add channel override if provided
            if channel:
                payload["channel"] = channel

            # Send request
            client = await self._get_client()
            response = await client.post(url, json=payload)

            # If blocks caused a 400, retry without them (text fallback)
            blocks_fallback = False
            blocks_error = ""
            if response.status_code == 400 and blocks:
                blocks_error = response.text[:200]
                logger.warning(
                    "slack_blocks_rejected",
                    status=response.status_code,
                    body=response.text[:500],
                )
                fallback_payload: dict[str, Any] = {
                    "username": username,
                    "icon_emoji": icon_emoji,
                    "attachments": [
                        {
                            "color": color,
                            "text": message,
                            "footer": "Mist Automation",
                            "ts": int(datetime.now(timezone.utc).timestamp()),
                        }
                    ],
                }
                if channel:
                    fallback_payload["channel"] = channel
                response = await client.post(url, json=fallback_payload)
                blocks_fallback = True

            response.raise_for_status()

            logger.info("slack_notification_sent", channel=channel, message_length=len(message), has_blocks=bool(blocks))

            result: dict[str, Any] = {
                "status": "sent",
                "platform": "slack",
                "channel": channel,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if blocks_fallback:
                result["blocks_fallback"] = True
                result["blocks_error"] = blocks_error
            return result

        except httpx.HTTPError as e:
            logger.error("slack_notification_failed", error=str(e))
            raise NotificationError(f"Failed to send Slack notification: {str(e)}")

    async def send_servicenow_notification(
        self,
        instance_url: Optional[str],
        username: Optional[str],
        password: Optional[str],
        table: str = "incident",
        data: Optional[dict[str, Any]] = None,
        short_description: Optional[str] = None,
        description: Optional[str] = None,
        priority: int = 3,
        urgency: int = 3,
    ) -> dict[str, Any]:
        """
        Create incident/record in ServiceNow.

        Args:
            instance_url: ServiceNow instance URL
            username: ServiceNow username
            password: ServiceNow password
            table: Table name (default: incident)
            data: Optional custom data dict
            short_description: Short description
            description: Full description
            priority: Priority (1-5)
            urgency: Urgency (1-3)

        Returns:
            Created record data

        Raises:
            NotificationError: If creation fails
        """
        url = instance_url or settings.servicenow_instance_url
        user = username or settings.servicenow_username
        pwd = password or settings.servicenow_password

        if not all([url, user, pwd]):
            raise ConfigurationError("ServiceNow credentials not configured")

        # Build endpoint URL
        endpoint = f"{url}/api/now/table/{table}"

        try:
            # Build payload
            if data:
                payload = data
            else:
                payload = {
                    "short_description": short_description or "Mist Automation Alert",
                    "description": description or "Alert from Mist Automation system",
                    "priority": priority,
                    "urgency": urgency,
                    "caller_id": user,
                }

            # Send request with basic auth
            client = await self._get_client()
            response = await client.post(
                endpoint,
                json=payload,
                auth=(user, pwd),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            response.raise_for_status()

            result = response.json()

            logger.info(
                "servicenow_record_created",
                table=table,
                sys_id=result.get("result", {}).get("sys_id"),
            )

            return {
                "status": "created",
                "platform": "servicenow",
                "table": table,
                "sys_id": result.get("result", {}).get("sys_id"),
                "number": result.get("result", {}).get("number"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except httpx.HTTPError as e:
            logger.error("servicenow_notification_failed", error=str(e))
            raise NotificationError(f"Failed to create ServiceNow record: {str(e)}")

    async def send_pagerduty_alert(
        self,
        integration_key: Optional[str],
        summary: str,
        severity: str = "warning",
        source: str = "Mist Automation",
        custom_details: Optional[dict[str, Any]] = None,
        dedup_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Send alert to PagerDuty.

        Args:
            integration_key: PagerDuty integration key
            summary: Alert summary
            severity: Severity (info, warning, error, critical)
            source: Alert source
            custom_details: Optional custom details
            dedup_key: Optional deduplication key

        Returns:
            Response data

        Raises:
            NotificationError: If alert fails
        """
        key = integration_key or settings.pagerduty_integration_key
        if not key:
            raise ConfigurationError("PagerDuty integration key not configured")

        # PagerDuty Events API v2 endpoint
        url = "https://events.pagerduty.com/v2/enqueue"

        try:
            # Build payload
            payload = {
                "routing_key": key,
                "event_action": "trigger",
                "payload": {
                    "summary": summary,
                    "severity": severity,
                    "source": source,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }

            # Add custom details if provided
            if custom_details:
                payload["payload"]["custom_details"] = custom_details

            # Add dedup key if provided
            if dedup_key:
                payload["dedup_key"] = dedup_key

            # Send request
            client = await self._get_client()
            response = await client.post(url, json=payload)
            response.raise_for_status()

            result = response.json()

            logger.info(
                "pagerduty_alert_sent",
                dedup_key=result.get("dedup_key"),
                status=result.get("status"),
            )

            return {
                "status": "triggered",
                "platform": "pagerduty",
                "dedup_key": result.get("dedup_key"),
                "message": result.get("message"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except httpx.HTTPError as e:
            logger.error("pagerduty_alert_failed", error=str(e))
            raise NotificationError(f"Failed to send PagerDuty alert: {str(e)}")

    async def send_webhook(
        self,
        url: str,
        payload: dict[str, Any],
        headers: Optional[dict[str, str]] = None,
        method: str = "POST",
    ) -> dict[str, Any]:
        """
        Send generic webhook.

        Args:
            url: Webhook URL
            payload: JSON payload
            headers: Optional custom headers
            method: HTTP method (POST, PUT)

        Returns:
            Response data

        Raises:
            NotificationError: If webhook fails
        """
        try:
            # Prepare headers
            request_headers = {"Content-Type": "application/json"}
            if headers:
                request_headers.update(headers)

            # Send request
            client = await self._get_client()
            if method.upper() == "POST":
                response = await client.post(url, json=payload, headers=request_headers)
            elif method.upper() == "PUT":
                response = await client.put(url, json=payload, headers=request_headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()

            logger.info("webhook_sent", url=url, method=method, status_code=response.status_code)

            return {
                "status": "sent",
                "platform": "webhook",
                "url": url,
                "status_code": response.status_code,
                "response": response.text[:1000],  # Limit response size
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except httpx.HTTPError as e:
            logger.error("webhook_failed", url=url, error=str(e))
            raise NotificationError(f"Failed to send webhook: {str(e)}")

    async def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        from_address: Optional[str] = None,
        html: bool = False,
    ) -> dict[str, Any]:
        """
        Send email notification.

        Note: This requires SMTP configuration which is not yet implemented.
        Placeholder for future implementation.

        Args:
            to: List of recipient email addresses
            subject: Email subject
            body: Email body
            from_address: Sender email address
            html: Whether body is HTML

        Returns:
            Response data

        Raises:
            NotImplementedError: Email not yet implemented
        """
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        if not settings.smtp_host:
            raise ConfigurationError("SMTP not configured")
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_address or settings.smtp_from_email
        msg["To"] = ", ".join(to) if isinstance(to, list) else to
        msg.attach(MIMEText(body, "html" if html else "plain"))
        await aiosmtplib.send(msg, hostname=settings.smtp_host, port=settings.smtp_port,
            username=settings.smtp_username, password=settings.smtp_password,
            use_tls=settings.smtp_use_tls)

        logger.info("email_sent", to=to, subject=subject)
        return {
            "status": "sent",
            "platform": "email",
            "to": to,
            "subject": subject,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def render_template(
        self,
        template_str: str,
        context: dict[str, Any],
    ) -> str:
        """
        Render notification message template.

        Args:
            template_str: Jinja2 template string
            context: Template context variables

        Returns:
            Rendered message

        Raises:
            NotificationError: If rendering fails
        """
        try:
            env = SandboxedEnvironment()
            template = env.from_string(template_str)
            rendered = template.render(**context)
            return rendered

        except Exception as e:
            logger.error("template_rendering_failed", error=str(e))
            raise NotificationError(f"Failed to render template: {str(e)}")

    async def test_slack_connection(self, webhook_url: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """
        Test Slack webhook connection.

        Args:
            webhook_url: Optional webhook URL to test

        Returns:
            tuple: (success, error_message)
        """
        try:
            await self.send_slack_notification(
                webhook_url=webhook_url,
                message="Test message from Mist Automation",
                color="good",
            )
            return True, None

        except Exception as e:
            return False, str(e)

    async def test_servicenow_connection(
        self,
        instance_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Test ServiceNow connection.

        Args:
            instance_url: Optional instance URL
            username: Optional username
            password: Optional password

        Returns:
            tuple: (success, error_message)
        """
        url = instance_url or settings.servicenow_instance_url
        user = username or settings.servicenow_username
        pwd = password or settings.servicenow_password

        if not all([url, user, pwd]):
            return False, "ServiceNow credentials not configured"

        try:
            # Try to query incident table (just to test auth)
            endpoint = f"{url}/api/now/table/incident?sysparm_limit=1"
            client = await self._get_client()
            response = await client.get(
                endpoint,
                auth=(user, pwd),
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()

            return True, None

        except Exception as e:
            return False, str(e)

    async def test_pagerduty_connection(
        self,
        integration_key: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Test PagerDuty integration.

        Args:
            integration_key: Optional integration key

        Returns:
            tuple: (success, error_message)
        """
        try:
            # Send test alert with resolve action
            key = integration_key or settings.pagerduty_integration_key
            if not key:
                return False, "PagerDuty integration key not configured"

            # Note: PagerDuty doesn't have a simple "test" endpoint
            # We would need to trigger and immediately resolve an alert
            # For now, just validate the key format
            if len(key) != 32:
                return False, "Invalid integration key format"

            return True, None

        except Exception as e:
            return False, str(e)

    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
