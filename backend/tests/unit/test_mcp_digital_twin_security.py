"""Unit tests for MCP `digital_twin` tool role enforcement and exception
sanitization (regression guards for review-pass fixes).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp.exceptions import ToolError

# Importing ``backup`` first triggers the mcp_server.server load in the same
# order production code uses, which breaks a top-level circular import that
# otherwise fires when ``digital_twin`` is the first tool imported.
from app.modules.mcp_server.tools import backup as _backup_tool  # noqa: F401
from app.modules.mcp_server.tools import digital_twin as dt_tool


class _FakeUser:
    def __init__(self, roles: list[str]):
        self.roles = roles


@pytest.fixture
def set_mcp_user():
    """Set ``mcp_user_id_var`` for a single test.

    We deliberately don't reset tokens: when ``set`` is called inside an
    async test (a different asyncio Context than the fixture teardown),
    ``reset`` raises "Token was created in a different Context". Each
    test gets its own asyncio event loop, so contextvars don't leak
    across tests.
    """

    def _set(value):
        dt_tool.mcp_user_id_var.set(value)

    return _set


@pytest.mark.unit
class TestMcpDigitalTwinAdminRole:
    """The MCP tool must enforce admin role — mirrors REST ``require_admin``.
    Previously any authenticated PAT holder could invoke simulate/approve.
    """

    async def _invoke(self, **kwargs):
        fn = getattr(dt_tool.digital_twin, "fn", dt_tool.digital_twin)
        return await fn(
            action=kwargs.get("action", "simulate"),
            action_type=kwargs.get("action_type", "create"),
            org_id=kwargs.get("org_id", "550e8400-e29b-41d4-a716-446655440000"),
            site_id=kwargs.get("site_id", "550e8400-e29b-41d4-a716-446655440001"),
            object_type=kwargs.get("object_type", "site_wlans"),
            payload=kwargs.get("payload", {"ssid": "test"}),
            object_id=kwargs.get("object_id"),
            changes=kwargs.get("changes"),
            session_id=kwargs.get("session_id"),
            ctx=kwargs.get("ctx", SimpleNamespace(client=None)),
        )

    async def test_missing_user_context_denied(self, set_mcp_user):
        set_mcp_user(None)
        with pytest.raises(ToolError, match="user context not available"):
            await self._invoke()

    async def test_malformed_user_id_denied_without_leak(self, set_mcp_user):
        """Regression: malformed user_id previously raised a bare Exception
        from PydanticObjectId(); the fix wraps it in try/except and returns
        a sanitized ToolError.
        """
        set_mcp_user("not-a-valid-object-id")
        with pytest.raises(ToolError, match="invalid user context"):
            await self._invoke()

    async def test_non_admin_user_denied(self, set_mcp_user, monkeypatch):
        set_mcp_user("507f1f77bcf86cd799439011")

        async def fake_user_get(_id):
            return _FakeUser(roles=["backup"])  # no admin

        from app.models.user import User as _User

        monkeypatch.setattr(_User, "get", fake_user_get)
        with pytest.raises(ToolError, match="admin role required"):
            await self._invoke()

    async def test_missing_user_denied(self, set_mcp_user, monkeypatch):
        set_mcp_user("507f1f77bcf86cd799439011")

        async def fake_user_get(_id):
            return None

        from app.models.user import User as _User

        monkeypatch.setattr(_User, "get", fake_user_get)
        with pytest.raises(ToolError, match="admin role required"):
            await self._invoke()


@pytest.mark.unit
class TestMcpDigitalTwinErrorSanitization:
    """The MCP tool must not leak raw ValueError/TwinApprovalError messages —
    mirrors REST ``_approve_error_response``.
    """

    async def _invoke_approve(self, session_id: str, *, monkeypatch, set_mcp_user, **_):
        fn = getattr(dt_tool.digital_twin, "fn", dt_tool.digital_twin)
        # Stub out admin gating so we reach the approve branch.
        set_mcp_user("507f1f77bcf86cd799439011")

        async def fake_user_get(_id):
            return _FakeUser(roles=["admin"])

        from app.models.user import User as _User

        monkeypatch.setattr(_User, "get", fake_user_get)

        # Stub SystemConfig.get_config (needed for default_org_id resolution).
        async def fake_get_config():
            return SimpleNamespace(mist_org_id="550e8400-e29b-41d4-a716-446655440000")

        from app.models.system import SystemConfig as _SystemConfig

        monkeypatch.setattr(_SystemConfig, "get_config", fake_get_config)

        # Stub _elicit to approve immediately.
        async def fake_elicit(*_args: Any, **_kwargs: Any):
            return None

        monkeypatch.setattr(dt_tool, "_elicit", fake_elicit)

        return await fn(
            action="approve",
            action_type=None,
            org_id=None,
            site_id=None,
            object_type=None,
            payload=None,
            object_id=None,
            changes=None,
            session_id=session_id,
            ctx=SimpleNamespace(client=None),
        )

    async def test_approve_maps_twin_approval_error_to_sanitized_message(self, monkeypatch, set_mcp_user):
        """Regression: approve path previously raised ToolError(str(exc)),
        leaking raw TwinApprovalError text. Fix uses _twin_approve_messages()
        to return deterministic sanitized messages.
        """
        from app.modules.digital_twin.services import twin_service

        session_id = "507f1f77bcf86cd799439020"

        # Stub get_session to return a fake session owned by the caller.
        class _Session:
            id = session_id
            user_id = "507f1f77bcf86cd799439011"
            staged_writes: list[Any] = []
            prediction_report = None
            remediation_count = 0
            overall_severity = "clean"
            affected_sites: list[str] = []

        async def fake_get_session(_id):
            sess = _Session()
            # str() below uses user_id as-is; the tool compares str(session.user_id)
            return sess

        monkeypatch.setattr(twin_service, "get_session", fake_get_session)

        # Make approve_and_execute raise the structured error.
        async def fake_approve(*_args: Any, **_kwargs: Any):
            raise twin_service.TwinApprovalError(
                twin_service.TwinApprovalErrorCode.BLOCKING_VALIDATION_ISSUES,
                "secret internal detail that must not leak",
            )

        monkeypatch.setattr(twin_service, "approve_and_execute", fake_approve)

        with pytest.raises(ToolError) as exc_info:
            await self._invoke_approve(session_id, monkeypatch=monkeypatch, set_mcp_user=set_mcp_user)

        # Sanitized message surfaces — raw exception text does not.
        assert "secret internal detail" not in str(exc_info.value)
        assert "blocking validation issues" in str(exc_info.value).lower()

    async def test_approve_maps_plain_value_error_to_generic_message(self, monkeypatch, set_mcp_user):
        from app.modules.digital_twin.services import twin_service

        session_id = "507f1f77bcf86cd799439030"

        class _Session:
            id = session_id
            user_id = "507f1f77bcf86cd799439011"
            staged_writes: list[Any] = []
            prediction_report = None
            remediation_count = 0
            overall_severity = "clean"
            affected_sites: list[str] = []

        async def fake_get_session(_id):
            return _Session()

        monkeypatch.setattr(twin_service, "get_session", fake_get_session)

        async def fake_approve(*_args: Any, **_kwargs: Any):
            raise ValueError("internal stack detail — should not leak")

        monkeypatch.setattr(twin_service, "approve_and_execute", fake_approve)

        with pytest.raises(ToolError) as exc_info:
            await self._invoke_approve(session_id, monkeypatch=monkeypatch, set_mcp_user=set_mcp_user)
        assert "internal stack detail" not in str(exc_info.value)
        assert "cannot be approved" in str(exc_info.value).lower()


@pytest.mark.unit
class TestMcpChangesSizeLimit:
    """The MCP simulate path must cap the `changes` list size so an LLM
    cannot stage unbounded writes (DoS / resource exhaustion surface).
    """

    def test_exceeding_max_changes_raises_toolerror(self):
        cap = dt_tool._MAX_CHANGES_PER_SIMULATE
        oversized = [
            {"action_type": "create", "object_type": "org_networks", "payload": {"name": f"n{i}"}}
            for i in range(cap + 1)
        ]
        with pytest.raises(ToolError, match="exceeds maximum size"):
            dt_tool._build_simulation_writes_from_changes(changes=oversized, org_id="org-1")
