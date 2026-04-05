"""
Pure ASGI middleware for request/response processing.

Avoids Starlette's BaseHTTPMiddleware which wraps send/receive in internal
channels that break streaming responses, SSE, and MCP streamable HTTP.
"""

import json
import time
import traceback
import uuid

import structlog

from app.core.exceptions import MistAutomationException

logger = structlog.get_logger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _json_error_body(status_code: int, error_type: str, message: str, details: dict | None = None) -> bytes:
    payload: dict = {"error": {"type": error_type, "message": message}}
    if details:
        payload["error"]["details"] = details
    return json.dumps(payload).encode("utf-8")


async def _send_json_response(send, status_code: int, body: bytes, extra_headers: list | None = None) -> None:
    headers = [[b"content-type", b"application/json"], [b"content-length", str(len(body)).encode()]]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


# ── Security Headers ─────────────────────────────────────────────────────────


class SecurityHeadersMiddleware:
    """Add security headers to all HTTP responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract host from ASGI headers for CSP
        host = ""
        for key, value in scope.get("headers", []):
            if key == b"host":
                host = value.decode("latin-1")
                break

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        [b"x-content-type-options", b"nosniff"],
                        [b"x-frame-options", b"DENY"],
                        [b"x-xss-protection", b"1; mode=block"],
                        [b"strict-transport-security", b"max-age=31536000; includeSubDomains"],
                        [b"referrer-policy", b"strict-origin-when-cross-origin"],
                        [
                            b"content-security-policy",
                            (
                                "default-src 'self'; script-src 'self'; "
                                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                "img-src 'self' data:; "
                                "font-src 'self' https://fonts.gstatic.com; "
                                f"connect-src 'self' wss://{host} ws://{host}; frame-ancestors 'none'"
                            ).encode(),
                        ],
                        [b"permissions-policy", b"camera=(), microphone=(), geolocation=()"],
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ── Maintenance Mode ─────────────────────────────────────────────────────────

_maintenance_cache: bool | None = None
_maintenance_cache_ts: float = 0.0
_MAINTENANCE_CACHE_TTL = 5.0


def set_maintenance_cache(value: bool) -> None:
    """Set the maintenance mode cache (called from admin settings update)."""
    global _maintenance_cache, _maintenance_cache_ts
    _maintenance_cache = value
    _maintenance_cache_ts = time.monotonic()


async def _get_maintenance_mode() -> bool:
    """Get maintenance mode with 5s cache to avoid DB hit on every request."""
    global _maintenance_cache, _maintenance_cache_ts
    now = time.monotonic()
    if _maintenance_cache is not None and (now - _maintenance_cache_ts) < _MAINTENANCE_CACHE_TTL:
        return _maintenance_cache
    from app.models.system import SystemConfig

    config = await SystemConfig.get_config()
    _maintenance_cache = config.maintenance_mode
    _maintenance_cache_ts = now
    return _maintenance_cache


class MaintenanceModeMiddleware:
    """Return 503 for non-admin/auth requests when maintenance mode is active."""

    _BYPASS_PREFIXES = ("/api/v1/auth/", "/api/v1/admin/", "/health", "/mcp")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path.startswith(p) for p in self._BYPASS_PREFIXES):
            await self.app(scope, receive, send)
            return

        if await _get_maintenance_mode():
            body = _json_error_body(503, "MaintenanceMode", "System is under maintenance.")
            await _send_json_response(send, 503, body, extra_headers=[[b"retry-after", b"3600"]])
            return

        await self.app(scope, receive, send)


# ── Exception Handler ────────────────────────────────────────────────────────


class ExceptionHandlerMiddleware:
    """Handle exceptions and return standardized error responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_tracking(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking)
        except MistAutomationException as e:
            request_id = scope.get("state", {}).get("request_id")
            logger.warning(
                "application_exception",
                exception_type=type(e).__name__,
                message=e.message,
                status_code=e.status_code,
                details=e.details,
                request_id=request_id,
            )
            if not response_started:
                body = _json_error_body(e.status_code, type(e).__name__, e.message, e.details)
                await _send_json_response(send, e.status_code, body)
        except Exception as e:
            request_id = scope.get("state", {}).get("request_id")
            logger.error(
                "unexpected_exception",
                exception_type=type(e).__name__,
                message=str(e),
                request_id=request_id,
                exception=traceback.format_exc(),
            )
            if not response_started:
                body = _json_error_body(500, "InternalServerError", "An unexpected error occurred")
                await _send_json_response(send, 500, body)


# ── Request Logging ──────────────────────────────────────────────────────────


class RequestLoggingMiddleware:
    """Log all HTTP requests and responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id

        # Extract client IP and user-agent from ASGI scope
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        user_agent = "unknown"
        for key, value in scope.get("headers", []):
            if key == b"user-agent":
                user_agent = value.decode("latin-1")
                break

        path = scope.get("path", "")
        method = scope.get("method", "")

        logger.info(
            "http_request_started",
            request_id=request_id,
            method=method,
            path=path,
            client_ip=client_ip,
            user_agent=user_agent,
        )

        start_time = time.time()
        status_code = 0

        async def send_with_logging(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
                # Inject X-Request-ID and X-Process-Time headers
                headers = list(message.get("headers", []))
                process_time = time.time() - start_time
                headers.extend(
                    [
                        [b"x-request-id", request_id.encode()],
                        [b"x-process-time", str(process_time).encode()],
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_logging)

        process_time = time.time() - start_time
        logger.info(
            "http_request_completed",
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            process_time=round(process_time, 4),
        )
