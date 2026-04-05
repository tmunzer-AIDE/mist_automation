"""
Lightweight webhook collector server.

Runs as a separate process/container to receive Mist webhooks on a
dedicated port, allowing internet exposure without exposing the UI/API.

Usage:
    uvicorn app.webhook_server:webhook_app --host 0.0.0.0 --port 9000
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.config import settings
from app.core.database import Database
from app.core.logger import configure_logging
from app.core.middleware import ExceptionHandlerMiddleware, RequestLoggingMiddleware

configure_logging()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def webhook_lifespan(_app: FastAPI):
    """Minimal lifespan: database connection only."""
    logger.info("webhook_collector_starting", port=settings.webhook_port)
    try:
        await Database.connect_db()
        logger.info("webhook_collector_ready")
        yield
    finally:
        logger.info("webhook_collector_shutting_down")
        await Database.close_db()
        logger.info("webhook_collector_shutdown_complete")


webhook_app = FastAPI(
    title="Mist Webhook Collector",
    version=settings.app_version,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=webhook_lifespan,
)

# Minimal middleware — no CORS, no security headers, no maintenance mode
webhook_app.add_middleware(RequestLoggingMiddleware)
webhook_app.add_middleware(ExceptionHandlerMiddleware)


@webhook_app.get("/health", tags=["Health"])
async def health_check():
    """Health check for the webhook collector."""
    return {
        "status": "healthy",
        "mode": "webhook-collector",
        "version": settings.app_version,
    }


# Mount the webhook router (reuses existing POST /webhooks/mist + ancillary endpoints)
from app.api.v1.webhooks import router as webhook_router  # noqa: E402

webhook_app.include_router(webhook_router, prefix=settings.api_v1_prefix)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.webhook_server:webhook_app",
        host="0.0.0.0",
        port=settings.webhook_port,
        log_level=settings.log_level.lower(),
    )
