"""
Pytest configuration and fixtures.
"""

import pytest
import pytest_asyncio
from typing import AsyncGenerator
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

# Route litellm calls through its httpx transport in tests. The default
# aiohttp transport leaks ClientSession instances per call (sessions are
# never closed); during interpreter shutdown GC then triggers noisy
# "Unclosed client session" logs that race with already-torn-down logging
# infrastructure ("sys.meta_path is None, Python is likely shutting down").
import litellm  # noqa: E402
litellm.disable_aiohttp_transport = True

from app.config import settings  # noqa: E402
from app.models.user import User  # noqa: E402
from app.modules import get_all_document_models  # noqa: E402


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
        roles=["admin", "automation", "backup", "post_deployment", "impact_analysis"],
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
    """Create a test workflow using the graph model."""
    from app.modules.automation.models.workflow import (
        Workflow, WorkflowStatus, WorkflowNode, WorkflowEdge,
        NodePosition, NodePort,
    )
    wf = Workflow(
        name="Test Workflow",
        created_by=test_user.id,
        status=WorkflowStatus.DRAFT,
        nodes=[
            WorkflowNode(
                id="trigger-1",
                type="trigger",
                name="Trigger",
                position=NodePosition(x=400, y=80),
                config={"trigger_type": "webhook", "webhook_type": "device-updowns"},
                output_ports=[NodePort(id="default")],
            ),
            WorkflowNode(
                id="action-1",
                type="webhook",
                name="notify",
                position=NodePosition(x=400, y=240),
                config={"webhook_url": "http://example.com"},
                output_ports=[NodePort(id="default")],
            ),
        ],
        edges=[
            WorkflowEdge(
                id="edge-1",
                source_node_id="trigger-1",
                source_port_id="default",
                target_node_id="action-1",
                target_port_id="input",
            ),
        ],
    )
    await wf.insert()
    return wf
