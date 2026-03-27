"""Unit tests for telemetry schemas — input validation and Flux injection prevention."""

import pytest
from pydantic import ValidationError

from app.modules.telemetry.schemas import (
    AggregateQueryParams,
    LatestStatsResponse,
    RangeQueryParams,
    TelemetrySettingsUpdate,
)


class TestRangeQueryParams:
    """Validate range query input sanitization."""

    def test_valid_defaults(self):
        p = RangeQueryParams(mac="aabbccddeeff", measurement="device_summary")
        assert p.mac == "aabbccddeeff"
        assert p.start == "-1h"
        assert p.end == "now()"

    def test_valid_colon_mac_normalized(self):
        p = RangeQueryParams(mac="aa:bb:cc:dd:ee:ff")
        assert p.mac == "aabbccddeeff"

    def test_invalid_mac_rejected(self):
        with pytest.raises(ValidationError, match="MAC"):
            RangeQueryParams(mac="INVALID")

    def test_invalid_mac_sql_injection(self):
        with pytest.raises(ValidationError, match="MAC"):
            RangeQueryParams(mac="aa:bb:cc:dd:ee:ff' OR 1=1 --")

    def test_invalid_measurement_rejected(self):
        with pytest.raises(ValidationError, match="measurement"):
            RangeQueryParams(mac="aabbccddeeff", measurement="'; DROP TABLE devices; --")

    def test_all_valid_measurements(self):
        for m in [
            "device_summary",
            "radio_stats",
            "port_stats",
            "module_stats",
            "gateway_wan",
            "gateway_health",
            "gateway_spu",
            "gateway_resources",
            "gateway_cluster",
            "gateway_dhcp",
        ]:
            p = RangeQueryParams(mac="aabbccddeeff", measurement=m)
            assert p.measurement == m

    def test_invalid_start_rejected(self):
        with pytest.raises(ValidationError, match="duration"):
            RangeQueryParams(mac="aabbccddeeff", start="DROP BUCKET")

    def test_valid_durations(self):
        for d in ["-1h", "-30m", "-7d", "-300s"]:
            p = RangeQueryParams(mac="aabbccddeeff", start=d)
            assert p.start == d

    def test_end_now_accepted(self):
        p = RangeQueryParams(mac="aabbccddeeff", end="now()")
        assert p.end == "now()"


class TestAggregateQueryParams:
    """Validate aggregate query input sanitization."""

    def test_valid_aggregate(self):
        p = AggregateQueryParams(
            site_id="12345678-1234-1234-1234-123456789012",
            field="cpu_util",
            agg="mean",
            window="5m",
        )
        assert p.agg == "mean"
        assert p.window == "5m"

    def test_invalid_site_id(self):
        with pytest.raises(ValidationError, match="UUID"):
            AggregateQueryParams(site_id="not-a-uuid", field="cpu_util")

    def test_invalid_field_injection(self):
        with pytest.raises(ValidationError, match="field"):
            AggregateQueryParams(
                site_id="12345678-1234-1234-1234-123456789012",
                field='cpu_util"; DROP BUCKET',
            )

    def test_invalid_agg(self):
        with pytest.raises(ValidationError, match="agg"):
            AggregateQueryParams(
                site_id="12345678-1234-1234-1234-123456789012",
                field="cpu_util",
                agg="DELETE",
            )

    def test_invalid_window(self):
        with pytest.raises(ValidationError, match="window"):
            AggregateQueryParams(
                site_id="12345678-1234-1234-1234-123456789012",
                field="cpu_util",
                window="abc",
            )

    def test_all_valid_aggregations(self):
        for a in ["mean", "max", "min", "sum", "count", "last"]:
            p = AggregateQueryParams(
                site_id="12345678-1234-1234-1234-123456789012",
                field="cpu_util",
                agg=a,
            )
            assert p.agg == a


class TestTelemetrySettingsUpdate:
    """Validate settings update schema."""

    def test_all_optional(self):
        s = TelemetrySettingsUpdate()
        assert s.telemetry_enabled is None

    def test_partial_update(self):
        s = TelemetrySettingsUpdate(telemetry_enabled=True)
        assert s.telemetry_enabled is True
        assert s.influxdb_url is None

    def test_retention_bounds(self):
        with pytest.raises(ValidationError):
            TelemetrySettingsUpdate(telemetry_retention_days=0)
        with pytest.raises(ValidationError):
            TelemetrySettingsUpdate(telemetry_retention_days=999)


class TestLatestStatsResponse:
    """Validate response serialization."""

    def test_empty_response(self):
        r = LatestStatsResponse(mac="aabbccddeeff", fresh=False)
        assert r.stats is None
        assert r.fresh is False

    def test_with_stats(self):
        r = LatestStatsResponse(
            mac="aabbccddeeff",
            fresh=True,
            updated_at=1700000000.0,
            stats={"cpu_util": 42, "mem_usage": 65},
        )
        assert r.stats["cpu_util"] == 42
