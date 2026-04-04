"""
Middleware for request/response processing.
"""

import time
import uuid
from collections.abc import Callable

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.exceptions import MistAutomationException

logger = structlog.get_logger(__name__)


class _SkipWebSocketMiddleware(BaseHTTPMiddleware):
    """Base middleware that skips WebSocket connections (BaseHTTPMiddleware is incompatible with them)."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.scope.get("type") == "websocket":
            return await call_next(request)
        return await self.process_request(request, call_next)

    async def process_request(self, request: Request, call_next: Callable) -> Response:
        raise NotImplementedError


class RequestLoggingMiddleware(_SkipWebSocketMiddleware):
    """Log all HTTP requests and responses."""

    async def process_request(self, request: Request, call_next: Callable) -> Response:
        # Generate request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Get client info
        client_ip = request.client.host if request.client else "unknown"

        # Log request
        logger.info(
            "http_request_started",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client_ip=client_ip,
            user_agent=request.headers.get("user-agent", "unknown"),
        )

        # Process request and measure time
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time

        # Add custom headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(process_time)

        # Log response
        logger.info(
            "http_request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            process_time=round(process_time, 4),
        )

        return response


class ExceptionHandlerMiddleware(_SkipWebSocketMiddleware):
    """Handle exceptions and return standardized error responses."""

    async def process_request(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except MistAutomationException as e:
            # Handle custom application exceptions
            logger.warning(
                "application_exception",
                exception_type=type(e).__name__,
                message=e.message,
                status_code=e.status_code,
                details=e.details,
                request_id=getattr(request.state, "request_id", None),
            )

            return JSONResponse(
                status_code=e.status_code,
                content={
                    "error": {
                        "type": type(e).__name__,
                        "message": e.message,
                        "details": e.details,
                    }
                },
            )
        except Exception as e:
            # Handle unexpected exceptions
            logger.error(
                "unexpected_exception",
                exception_type=type(e).__name__,
                message=str(e),
                request_id=getattr(request.state, "request_id", None),
                exc_info=True,
            )

            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "type": "InternalServerError",
                        "message": "An unexpected error occurred",
                    }
                },
            )


class SecurityHeadersMiddleware(_SkipWebSocketMiddleware):
    """Add security headers to all responses."""

    async def process_request(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data:; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self'; frame-ancestors 'none'"
        )
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        return response


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


class MaintenanceModeMiddleware(_SkipWebSocketMiddleware):
    """Return 503 for non-admin/auth requests when maintenance mode is active."""

    _BYPASS_PREFIXES = ("/api/v1/auth/", "/api/v1/admin/", "/health", "/mcp")

    async def process_request(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in self._BYPASS_PREFIXES):
            return await call_next(request)
        if await _get_maintenance_mode():
            return JSONResponse(
                status_code=503,
                content={"error": {"type": "MaintenanceMode", "message": "System is under maintenance."}},
                headers={"Retry-After": "3600"},
            )
        return await call_next(request)
