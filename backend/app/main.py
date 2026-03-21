"""
Main FastAPI application entry point.
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.database import Database
from app.core.logger import configure_logging
from app.core.middleware import (
    ExceptionHandlerMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)

# Configure structured logging
configure_logging()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Application lifespan context manager.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("application_starting", version=settings.app_version, environment=settings.environment)

    try:
        # Connect to database
        await Database.connect_db()
        logger.info("database_connection_established")

        # Start Smee.io client if enabled
        try:
            from app.models.system import SystemConfig

            config = await SystemConfig.get_config()
            if config.smee_enabled and config.smee_channel_url:
                from app.core.smee_service import start_smee

                target = f"http://127.0.0.1:8000{settings.api_v1_prefix}/webhooks/mist"
                await start_smee(config.smee_channel_url, target)
                logger.info("smee_client_auto_started", channel=config.smee_channel_url)
        except Exception as e:
            logger.warning("smee_auto_start_failed", error=str(e))

        # Load Mist OpenAPI Specification (for variable autocomplete + mock responses)
        if settings.mist_oas_url:
            try:
                from app.modules.automation.services.oas_service import OASService

                await OASService.load(settings.mist_oas_url)
            except Exception as e:
                logger.warning("oas_load_failed", error=str(e))

        # Start APScheduler (cron workflows + scheduled backups)
        try:
            from app.workers import start_scheduler

            await start_scheduler()
            logger.info("scheduler_started")
        except Exception as e:
            logger.warning("scheduler_start_failed", error=str(e))

        # Start WebSocket heartbeat
        from app.core.websocket import ws_manager

        ws_manager.start_heartbeat()
        logger.info("websocket_heartbeat_started")

        logger.info("application_started_successfully")

        yield

    finally:
        # Shutdown
        logger.info("application_shutting_down")

        # Stop scheduler
        try:
            from app.workers import stop_scheduler

            await stop_scheduler()
        except Exception:
            pass

        # Stop WebSocket heartbeat
        try:
            from app.core.websocket import ws_manager as _ws_mgr

            _ws_mgr.stop_heartbeat()
        except Exception:
            pass

        # Stop Smee.io client if running
        try:
            from app.core.smee_service import stop_smee

            await stop_smee()
        except Exception:
            pass

        # Close database connection
        await Database.close_db()

        logger.info("application_shutdown_complete")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Comprehensive web application for automating Juniper Mist operations and managing configuration backups",
    docs_url=f"{settings.api_v1_prefix}/docs" if settings.debug else None,
    redoc_url=f"{settings.api_v1_prefix}/redoc" if settings.debug else None,
    openapi_url=f"{settings.api_v1_prefix}/openapi.json" if settings.debug else None,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-Process-Time"],
)

# Add custom middleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ExceptionHandlerMiddleware)
app.add_middleware(RequestLoggingMiddleware)


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    from app.models.user import User

    try:
        user_count = await User.find().count()
        is_initialized = user_count > 0
    except Exception:
        is_initialized = False

    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "is_initialized": is_initialized,
        "password_policy": {
            "min_length": settings.min_password_length,
            "require_uppercase": settings.require_uppercase,
            "require_lowercase": settings.require_lowercase,
            "require_digits": settings.require_digits,
            "require_special_chars": settings.require_special_chars,
        },
    }


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint."""
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "docs": f"{settings.api_v1_prefix}/docs" if settings.debug else None,
    }


# Register routers from module registry
from app.modules import MODULES

for _module in MODULES:
    if not _module.enabled:
        continue
    try:
        app.include_router(
            _module.get_router(),
            prefix=settings.api_v1_prefix,
            tags=_module.tags,
        )
    except Exception as e:
        logger.warning("module_load_failed", module=_module.name, error=str(e))

logger.info("api_routers_registered")

# Mount MCP server
try:
    from app.modules.mcp_server.server import mcp as _mcp_server

    app.mount("/mcp", _mcp_server.http_app(path="/"))
    logger.info("mcp_server_mounted", path="/mcp")
except Exception as e:
    logger.warning("mcp_server_mount_failed", error=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
