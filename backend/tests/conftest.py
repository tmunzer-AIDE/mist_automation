"""
Pytest configuration and fixtures.
"""

import pytest
import pytest_asyncio
from typing import AsyncGenerator
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.config import settings
from app.models.user import User
from app.modules import get_all_document_models


@pytest.fixture(scope="session")
def anyio_backend():
    """Use asyncio backend for pytest-asyncio."""
    return "asyncio"


@pytest_asyncio.fixture(scope="function")
async def test_db() -> AsyncGenerator:
    """
    Create a test database for each test function.
    Drops the database after the test completes.
    """
    # Use a separate test database
    test_db_name = f"{settings.mongodb_db_name}_test"

    # Connect to MongoDB (use connection URL with credentials if configured)
    client = AsyncIOMotorClient(settings.mongodb_connection_url)

    # Initialize Beanie with all models from the module registry
    await init_beanie(
        database=client[test_db_name],
        document_models=get_all_document_models(),
    )

    yield client[test_db_name]

    # Cleanup: drop test database
    await client.drop_database(test_db_name)
    client.close()


@pytest_asyncio.fixture
async def test_user(test_db) -> User:
    """Create a test user."""
    import bcrypt
    # Use bcrypt directly to avoid passlib version incompatibility
    password_hash = bcrypt.hashpw(b"Test123!", bcrypt.gensalt()).decode()

    user = User(
        email="test@example.com",
        password_hash=password_hash,
        roles=["admin", "automation", "backup"],
        timezone="UTC",
        is_active=True,
    )
    await user.insert()
    return user


@pytest_asyncio.fixture
async def client(test_db, test_user):
    from contextlib import asynccontextmanager
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.dependencies import get_current_user_from_token

    @asynccontextmanager
    async def mock_lifespan(app): yield

    original = app.router.lifespan_context
    app.router.lifespan_context = mock_lifespan
    app.dependency_overrides[get_current_user_from_token] = lambda: test_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.router.lifespan_context = original
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_token(test_user):
    from app.core.security import create_access_token
    token, _ = create_access_token({"sub": str(test_user.id), "email": test_user.email})
    return token


@pytest_asyncio.fixture
async def test_workflow(test_db, test_user):
    from app.models.workflow import (Workflow, WorkflowStatus, WorkflowTrigger,
        TriggerType, WorkflowAction, ActionType)
    wf = Workflow(
        name="Test Workflow", created_by=test_user.id,
        status=WorkflowStatus.DRAFT,
        trigger=WorkflowTrigger(type=TriggerType.WEBHOOK, webhook_type="device-updowns"),
        filters=[], secondary_filters=[],
        actions=[WorkflowAction(name="notify", type=ActionType.WEBHOOK,
                                webhook_url="http://example.com")],
    )
    await wf.insert()
    return wf
