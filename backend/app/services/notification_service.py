"""
Notification service for external integrations (Slack, ServiceNow, PagerDuty).
"""

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from app.config import settings
from app.core.exceptions import ConfigurationError, NotificationError

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
    async def _resolve_verify(probe_url: str = "https://hooks.slack.com") -> str | bool:
        """Try TLS options in order: CA_CERT_PATH → default → disabled.

        Same fallback strategy as SmeeClient for ZScaler/TLS-intercepting proxies.
        """

        from app.core.smee_service import _build_verify_options

        options = _build_verify_options()
        for option in options:
            try:
                async with httpx.AsyncClient(verify=option) as client:
                    await client.head(probe_url, timeout=10)
                return option
            except Exception:
                continue

        return False

    async def send_slack_notification(
        self,
        webhook_url: str | None,
        message: str,
        channel: str | None = None,
        username: str = "Mist Automation",
        icon_emoji: str = ":robot_face:",
        color: str = "good",
        fields: list[dict[str, Any]] | None = None,
        blocks: list[dict[str, Any]] | None = None,
        actions: list[dict[str, Any]] | None = None,
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
            actions: Optional list of interactive button dicts
                (each: {text, action_id, value, style?})

        Returns:
            Response data

        Raises:
            NotificationError: If notification fails
        """
        url = webhook_url or settings.slack_webhook_url
        if not url:
            raise ConfigurationError("Slack webhook URL not configured")

        from app.utils.url_safety import validate_outbound_url

        validate_outbound_url(url)

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

            # Append interactive action buttons if provided
            if actions:
                action_elements = []
                for act in actions:
                    btn: dict[str, Any] = {
                        "type": "button",
                        "text": {"type": "plain_text", "text": act["text"]},
                        "action_id": act["action_id"],
                        "value": act.get("value", ""),
                    }
                    if act.get("style"):
                        btn["style"] = act["style"]  # "primary" or "danger"
                    action_elements.append(btn)

                actions_block = {"type": "actions", "elements": action_elements}
                if "blocks" in payload:
                    payload["blocks"].append(actions_block)
                else:
                    # Promote to blocks-based payload so actions render
                    payload["blocks"] = [
                        {"type": "section", "text": {"type": "mrkdwn", "text": message}},
                        actions_block,
                    ]

            # Add channel override if provided
            if channel:
                payload["channel"] = channel

            logger.debug(
                "slack_payload",
                has_blocks=bool(blocks),
                block_count=len(blocks) if blocks else 0,
                has_actions=bool(actions),
                message_length=len(message),
            )

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
                # Extract text from blocks if message is empty
                fallback_text = message
                if not fallback_text.strip() and blocks:
                    texts = [
                        b.get("text", {}).get("text", "")
                        for b in blocks
                        if b.get("type") == "section" and isinstance(b.get("text"), dict)
                    ]
                    fallback_text = "\n".join(t for t in texts if t)[:3000] or message

                fallback_payload: dict[str, Any] = {
                    "username": username,
                    "icon_emoji": icon_emoji,
                    "attachments": [
                        {
                            "color": color,
                            "text": fallback_text,
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

            logger.info(
                "slack_notification_sent", channel=channel, message_length=len(message), has_blocks=bool(blocks)
            )

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
        instance_url: str | None,
        username: str | None,
        password: str | None,
        table: str = "incident",
        data: dict[str, Any] | None = None,
        short_description: str | None = None,
        description: str | None = None,
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

        # Build endpoint URL and validate against SSRF
        endpoint = f"{url}/api/now/table/{table}"
        from app.utils.url_safety import validate_outbound_url

        validate_outbound_url(endpoint)

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
        integration_key: str | None,
        summary: str,
        severity: str = "warning",
        source: str = "Mist Automation",
        custom_details: dict[str, Any] | None = None,
        dedup_key: str | None = None,
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
        headers: dict[str, str] | None = None,
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
        from app.utils.url_safety import validate_outbound_url

        validate_outbound_url(url)

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
        from_address: str | None = None,
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
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        import aiosmtplib

        # Prefer DB config (SystemConfig), fall back to env vars
        from app.models.system import SystemConfig
        from app.core.security import decrypt_sensitive_data

        config = await SystemConfig.get_config()
        host = config.smtp_host or settings.smtp_host
        if not host:
            raise ConfigurationError("SMTP not configured")

        port = config.smtp_port if config.smtp_host else settings.smtp_port
        username = config.smtp_username or settings.smtp_username
        password = (
            decrypt_sensitive_data(config.smtp_password) if config.smtp_password else None
        ) or settings.smtp_password
        sender = from_address or (config.smtp_from_email if config.smtp_host else None) or settings.smtp_from_email
        use_tls = config.smtp_use_tls if config.smtp_host else settings.smtp_use_tls

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = ", ".join(to) if isinstance(to, list) else to
        msg.attach(MIMEText(body, "html" if html else "plain"))
        await aiosmtplib.send(
            msg,
            hostname=host,
            port=port,
            username=username,
            password=password,
            use_tls=use_tls,
        )

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
            from app.utils.variables import create_jinja_env

            env = create_jinja_env()
            template = env.from_string(template_str)
            rendered = template.render(**context)
            return rendered

        except Exception as e:
            logger.error("template_rendering_failed", error=str(e))
            raise NotificationError(f"Failed to render template: {str(e)}")

    async def test_slack_connection(self, webhook_url: str | None = None) -> tuple[bool, str | None]:
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
            logger.error("slack_connection_test_failed", error=str(e))
            return False, "Slack connection test failed"

    async def test_servicenow_connection(
        self,
        instance_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> tuple[bool, str | None]:
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
            from app.utils.url_safety import validate_outbound_url

            validate_outbound_url(endpoint)
            client = await self._get_client()
            response = await client.get(
                endpoint,
                auth=(user, pwd),
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()

            return True, None

        except Exception as e:
            logger.error("servicenow_connection_test_failed", error=str(e))
            return False, "ServiceNow connection test failed"

    async def test_pagerduty_connection(
        self,
        integration_key: str | None = None,
    ) -> tuple[bool, str | None]:
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
            logger.error("pagerduty_connection_test_failed", error=str(e))
            return False, "PagerDuty connection test failed"

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
