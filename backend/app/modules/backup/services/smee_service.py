"""
Smee.io client service for forwarding webhooks in development.

Connects to a Smee.io channel via SSE (Server-Sent Events) and replays
incoming events to the local webhook endpoint.
"""

import asyncio
import json

import ssl

import httpx
import structlog

logger = structlog.get_logger(__name__)


def _build_verify_options() -> list:
    """Return a list of httpx ``verify`` values to try in order.

    Resolution order:
    1. ``CA_CERT_PATH`` from .env – explicit PEM bundle (e.g. exported ZScaler root)
    2. OS default trust store     – ``True`` lets httpx/ssl use system certs
    3. Disabled verification      – ``False`` as last resort for dev behind
       proxies whose CA triggers strict-mode SSL errors (e.g. non-critical
       Basic Constraints)

    The caller should try each option and fall back to the next one if the
    TLS handshake fails.
    """
    from app.config import settings

    options: list = []
    if settings.ca_cert_path:
        options.append(settings.ca_cert_path)   # httpx accepts a file path
    options.append(True)                         # default certifi / OS store
    options.append(False)                        # no verification
    return options


class SmeeClient:
    """Async Smee.io SSE client that forwards events to a local endpoint."""

    def __init__(self, channel_url: str, target_url: str):
        self.channel_url = channel_url
        self.target_url = target_url
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._running = True
        self._task = asyncio.create_task(self._listen())
        logger.info("smee_client_started", channel=self.channel_url, target=self.target_url)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("smee_client_stopped")

    async def _listen(self) -> None:
        """Connect to Smee SSE stream and forward events."""
        verify = await self._resolve_verify()
        backoff = 1
        while self._running:
            try:
                async with httpx.AsyncClient(timeout=None, verify=verify) as client:
                    async with client.stream(
                        "GET",
                        self.channel_url,
                        headers={"Accept": "text/event-stream"},
                    ) as response:
                        response.raise_for_status()
                        backoff = 1
                        logger.info("smee_connected", channel=self.channel_url)

                        event_data = ""
                        async for line in response.aiter_lines():
                            if not self._running:
                                return

                            if line.startswith("data: "):
                                event_data = line[6:]
                            elif line == "" and event_data:
                                await self._forward(event_data, client)
                                event_data = ""

            except asyncio.CancelledError:
                return
            except httpx.HTTPStatusError as exc:
                logger.error("smee_http_error", status=exc.response.status_code)
            except Exception as exc:
                logger.warning("smee_connection_lost", error=str(exc))

            if self._running:
                logger.info("smee_reconnecting", backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _resolve_verify(self) -> ssl.SSLContext | str | bool:
        """Try each verify option with a real HEAD request; return the first that works."""
        options = _build_verify_options()
        for option in options:
            try:
                async with httpx.AsyncClient(verify=option) as client:
                    await client.head(self.channel_url, timeout=10)
                label = option if isinstance(option, (str, bool)) else "ssl_context"
                logger.info("smee_ssl_resolved", verify=str(label))
                return option
            except Exception as exc:
                label = option if isinstance(option, (str, bool)) else "ssl_context"
                logger.debug("smee_ssl_option_failed", verify=str(label), error=str(exc))

        # All options exhausted — use False
        logger.warning("smee_ssl_all_failed", msg="All TLS options failed; disabling verification")
        return False

    async def _forward(self, raw: str, client: httpx.AsyncClient) -> None:
        """Forward an SSE event payload to the local webhook endpoint."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        # Smee wraps the original request — extract body and headers.
        # Smee.io sends keepalive/heartbeat SSE events that don't carry a
        # "body" key.  Skip those to avoid forwarding empty payloads.
        if "body" not in data:
            return

        body = data["body"]

        # Build forwarding headers (keep content-type and Mist signature).
        # Mark the request as smee-forwarded so the webhook endpoint can
        # skip HMAC verification (the body has been round-tripped through
        # JSON parse/serialize and the signature won't match).
        forward_headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Forwarded-By": "smee",
        }
        nested_headers: dict = data.get("headers", {})
        for key in ("x-mist-signature", "x-mist-signature-v2"):
            value = nested_headers.get(key) or data.get(key)
            if value:
                forward_headers[key] = value

        # Preserve the original body bytes so the HMAC signature stays valid.
        # If "body" came from smee as a dict, we must re-serialize — but use
        # separators without trailing whitespace to stay close to the original.
        if isinstance(body, str):
            content = body
        elif isinstance(body, dict):
            content = json.dumps(body, separators=(",", ":"))
        else:
            content = str(body)

        try:
            resp = await client.post(
                self.target_url,
                content=content,
                headers=forward_headers,
            )
            logger.debug(
                "smee_event_forwarded",
                status=resp.status_code,
                topic=body.get("topic", "unknown") if isinstance(body, dict) else "unknown",
            )
        except Exception as exc:
            logger.warning("smee_forward_failed", error=str(exc))


# ── Singleton manager ────────────────────────────────────────────────────────

_client: SmeeClient | None = None


def get_smee_client() -> SmeeClient | None:
    return _client


def _validate_smee_url(url: str) -> None:
    """Ensure the Smee channel URL is a valid smee.io URL."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "smee.io":
        raise ValueError("Smee URL must be an https://smee.io/ URL")


async def start_smee(channel_url: str, target_url: str) -> SmeeClient:
    global _client
    _validate_smee_url(channel_url)
    if _client and _client.is_running:
        await _client.stop()
    _client = SmeeClient(channel_url, target_url)
    await _client.start()
    return _client


async def stop_smee() -> None:
    global _client
    if _client:
        await _client.stop()
        _client = None
