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


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all HTTP requests and responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip WebSocket connections — BaseHTTPMiddleware is incompatible with them
        if request.scope.get("type") == "websocket":
            return await call_next(request)
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


class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """Handle exceptions and return standardized error responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip WebSocket connections — BaseHTTPMiddleware is incompatible with them
        if request.scope.get("type") == "websocket":
            return await call_next(request)
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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip WebSocket connections — BaseHTTPMiddleware is incompatible with them
        if request.scope.get("type") == "websocket":
            return await call_next(request)
        response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        return response
