from types import SimpleNamespace

import pytest

from app.modules.backup.services.restore_service import RestoreService


class _FakeMistService:
    def __init__(self):
        self.org_id = "org-1"


@pytest.mark.asyncio
async def test_simulate_restore_defaults_execution_safe_false_without_report(monkeypatch):
    service = RestoreService(_FakeMistService())

    backup = SimpleNamespace(
        object_id="obj-1",
        object_type="wlans",
        object_name="Guest",
        version=7,
        org_id="org-1",
        site_id="site-1",
        configuration={"ssid": "Guest", "enabled": True},
    )

    async def _fake_validate_restore(_backup):
        return {"exists_in_mist": True, "warnings": []}

    monkeypatch.setattr(service, "_validate_restore", _fake_validate_restore)

    async def _fake_simulate(**_kwargs):
        return SimpleNamespace(
            id="507f1f77bcf86cd799439011",
            prediction_report=None,
            overall_severity="error",
        )

    import app.modules.digital_twin.services.twin_service as twin_service

    monkeypatch.setattr(twin_service, "simulate", _fake_simulate)

    result = await service.simulate_restore(backup=backup, user_id="user-1", cascade=False)

    assert result["execution_safe"] is False
    assert "without a prediction report" in result["summary"]
    assert any("prediction report was not generated" in w.lower() for w in result["warnings"])
