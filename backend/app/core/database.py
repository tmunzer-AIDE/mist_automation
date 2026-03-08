"""
Database connection and session management.
Handles MongoDB connection using Motor (async) and Beanie ODM.
"""

import structlog
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings

logger = structlog.get_logger(__name__)


class Database:
    """MongoDB database connection manager."""

    client: AsyncIOMotorClient | None = None

    @classmethod
    async def connect_db(cls):
        """
        Connect to MongoDB and initialize Beanie ODM.
        Called on application startup.
        """
        try:
            logger.info("connecting_to_mongodb", url=settings.mongodb_url, db=settings.mongodb_db_name)

            cls.client = AsyncIOMotorClient(
                settings.mongodb_connection_url,
                minPoolSize=settings.mongodb_min_pool_size,
                maxPoolSize=settings.mongodb_max_pool_size,
            )

            # Import all models for Beanie initialization
            from app.models.backup import BackupConfig, BackupObject
            from app.models.execution import WorkflowExecution
            from app.models.session import UserSession
            from app.models.system import AuditLog, SystemConfig
            from app.models.user import User
            from app.models.webhook import WebhookEvent
            from app.models.workflow import Workflow

            # Initialize Beanie with all document models
            await init_beanie(
                database=cls.client[settings.mongodb_db_name],
                document_models=[
                    User,
                    UserSession,
                    Workflow,
                    WorkflowExecution,
                    WebhookEvent,
                    BackupObject,
                    BackupConfig,
                    SystemConfig,
                    AuditLog,
                ]
            )

            logger.info("mongodb_connected_successfully")

        except Exception as e:
            logger.error("mongodb_connection_failed", error=str(e))
            raise

    @classmethod
    async def close_db(cls):
        """
        Close MongoDB connection.
        Called on application shutdown.
        """
        if cls.client:
            logger.info("closing_mongodb_connection")
            cls.client.close()
            logger.info("mongodb_connection_closed")

    @classmethod
    def get_client(cls) -> AsyncIOMotorClient:
        """Get the MongoDB client instance."""
        if cls.client is None:
            raise RuntimeError("Database not initialized. Call connect_db() first.")
        return cls.client

    @classmethod
    def get_database(cls):
        """Get the database instance."""
        client = cls.get_client()
        return client[settings.mongodb_db_name]


async def get_database():
    """
    Dependency injection for database access.
    Use in FastAPI route handlers.
    """
    return Database.get_database()
