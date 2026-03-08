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

        # Additional startup tasks can be added here
        # - Initialize Redis connection
        # - Start background workers
        # - Load system configuration

        logger.info("application_started_successfully")

        yield

    finally:
        # Shutdown
        logger.info("application_shutting_down")

        # Close database connection
        await Database.close_db()

        # Additional cleanup tasks can be added here

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
    allow_methods=["*"],
    allow_headers=["*"],
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
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
