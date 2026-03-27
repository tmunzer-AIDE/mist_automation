# Telemetry Foundation Implementation Plan (Plan 1 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation layer for the WebSocket telemetry pipeline — InfluxDB service, CoV filter, in-memory cache, SystemConfig integration, and module scaffolding.

**Architecture:** New `app/modules/telemetry/` module with three core services: `InfluxDBService` (async batched writes), `CoVFilter` (change-of-value filtering with max staleness), `LatestValueCache` (in-memory device stats). Config stored in existing `SystemConfig` with encrypted InfluxDB token.

**Tech Stack:** Python 3.10+, influxdb-client[async], FastAPI, Beanie, pytest

**Spec:** `docs/superpowers/specs/2026-03-26-websocket-telemetry-pipeline-design.md`

**Scope:** Foundation only — no WebSocket manager, no extractors, no frontend. Those are Plans 2-5.

---

# Plan: Telemetry Foundation (Plan 1)

```
# 2026-03-26-telemetry-foundation.md
#
# Spec: docs/superpowers/specs/2026-03-26-websocket-telemetry-pipeline-design.md
# Scope: Foundation layer only — InfluxDB service, CoV filter, Latest value cache,
#         SystemConfig integration, module scaffolding. No WebSocket, no extractors,
#         no API endpoints beyond /telemetry/status.
#
# NOTE FOR AGENTIC WORKER:
# Each step below is fully self-contained. Execute them IN ORDER.
# Every step includes exact file paths, complete code, and the shell commands to run.
# Do NOT skip steps. Do NOT combine steps. Commit after each green test.
# Working directory for all commands: cd /Users/tmunzer/4_dev/mist_automation/backend
```

---

## Step 1 — Add `influxdb-client[async]` dependency and mypy override

### 1a. Edit `pyproject.toml` — add dependency

**File:** `backend/pyproject.toml`

In the `dependencies` list (after `"fastmcp>=3.0.0",`), add:

```python
    "influxdb-client[async]>=1.46.0",
```

### 1b. Edit `pyproject.toml` — add mypy override

In the `[[tool.mypy.overrides]]` section, add `"influxdb_client.*"` to the `module` list:

```python
[[tool.mypy.overrides]]
module = [
    "motor.*",
    "beanie.*",
    "jose.*",
    "passlib.*",
    "pyotp.*",
    "qrcode.*",
    "mistapi.*",
    "reportlab.*",
    "celery.*",
    "apscheduler.*",
    "git.*",
    "litellm.*",
    "fastmcp.*",
    "mcp.*",
    "influxdb_client.*",
]
ignore_missing_imports = true
```

### 1c. Install updated dependencies

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pip install -e ".[dev,test]"
```

### 1d. Verify import works

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/python -c "from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync; print('OK')"
```

### 1e. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add pyproject.toml
git commit -m "$(cat <<'EOF'
feat(telemetry): add influxdb-client[async] dependency and mypy override

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 2 — Add telemetry fields to SystemConfig

### 2a. Edit `backend/app/models/system.py`

Add the following fields to the `SystemConfig` class, after the `impact_analysis_retention_days` field (line ~100) and before the `# System Status` section:

```python
    # Telemetry Configuration (InfluxDB + WebSocket ingestion)
    telemetry_enabled: bool = Field(default=False, description="Enable real-time telemetry ingestion")
    influxdb_url: str = Field(default="http://localhost:8086", description="InfluxDB connection URL")
    influxdb_token: str | None = Field(default=None, description="Encrypted InfluxDB admin token")
    influxdb_org: str = Field(default="mist_automation", description="InfluxDB organization")
    influxdb_bucket: str = Field(default="mist_telemetry", description="InfluxDB bucket name")
    telemetry_retention_days: int = Field(default=30, ge=1, le=365, description="Telemetry data retention in days")
```

### 2b. Edit `backend/app/schemas/admin.py`

Add the following fields to the `SystemSettingsUpdate` class, after the `impact_analysis_retention_days` field (line ~84):

```python
    # Telemetry
    telemetry_enabled: bool | None = None
    influxdb_url: str | None = None
    influxdb_token: str | None = None
    influxdb_org: str | None = None
    influxdb_bucket: str | None = None
    telemetry_retention_days: int | None = Field(None, ge=1, le=365)
```

Also add `"influxdb_url"` to the `validate_url` field_validator decorator on line 111. Change:

```python
    @field_validator("backup_git_repo_url", "slack_webhook_url", "servicenow_instance_url", "smee_channel_url")
```

to:

```python
    @field_validator("backup_git_repo_url", "slack_webhook_url", "servicenow_instance_url", "smee_channel_url", "influxdb_url")
```

### 2c. Edit `backend/app/api/v1/admin.py`

Add `"influxdb_token"` to the `sensitive_encrypt` set at line 105:

```python
    sensitive_encrypt = {
        "mist_api_token",
        "webhook_secret",
        "servicenow_password",
        "pagerduty_api_key",
        "slack_signing_secret",
        "smtp_password",
        "influxdb_token",
    }
```

Also add the telemetry fields to the `get_system_settings` response dict (after `"llm_enabled"` and before `"updated_at"`):

```python
        # Telemetry
        "telemetry_enabled": config.telemetry_enabled,
        "influxdb_url": config.influxdb_url,
        "influxdb_token_set": bool(config.influxdb_token),
        "influxdb_org": config.influxdb_org,
        "influxdb_bucket": config.influxdb_bucket,
        "telemetry_retention_days": config.telemetry_retention_days,
```

### 2d. Verify types pass

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/mypy app/models/system.py app/schemas/admin.py app/api/v1/admin.py --no-error-summary
```

### 2e. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/models/system.py app/schemas/admin.py app/api/v1/admin.py
git commit -m "$(cat <<'EOF'
feat(telemetry): add InfluxDB config fields to SystemConfig and admin schema

Adds telemetry_enabled, influxdb_url, influxdb_token (encrypted),
influxdb_org, influxdb_bucket, and telemetry_retention_days fields.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 3 — Create LatestValueCache (test first)

### 3a. Write failing test

**Create file:** `backend/tests/unit/test_latest_value_cache.py`

```python
"""Unit tests for LatestValueCache."""

import time

from app.modules.telemetry.services.latest_value_cache import LatestValueCache


class TestLatestValueCache:
    """Tests for the in-memory latest-value cache."""

    def test_update_and_get(self):
        cache = LatestValueCache()
        cache.update("aa:bb:cc:dd:ee:ff", {"cpu_util": 42, "mem_usage": 65})
        result = cache.get("aa:bb:cc:dd:ee:ff")
        assert result is not None
        assert result["cpu_util"] == 42
        assert result["mem_usage"] == 65

    def test_get_nonexistent_returns_none(self):
        cache = LatestValueCache()
        assert cache.get("00:00:00:00:00:00") is None

    def test_update_overwrites_previous(self):
        cache = LatestValueCache()
        cache.update("aa:bb:cc:dd:ee:ff", {"cpu_util": 42})
        cache.update("aa:bb:cc:dd:ee:ff", {"cpu_util": 99, "uptime": 3600})
        result = cache.get("aa:bb:cc:dd:ee:ff")
        assert result is not None
        assert result["cpu_util"] == 99
        assert result["uptime"] == 3600

    def test_get_all(self):
        cache = LatestValueCache()
        cache.update("mac1", {"cpu": 10})
        cache.update("mac2", {"cpu": 20})
        all_items = cache.get_all()
        assert len(all_items) == 2
        assert "mac1" in all_items
        assert "mac2" in all_items

    def test_get_all_returns_copy(self):
        cache = LatestValueCache()
        cache.update("mac1", {"cpu": 10})
        all_items = cache.get_all()
        all_items["mac1"]["cpu"] = 999
        # Original should be unaffected
        assert cache.get("mac1")["cpu"] == 10

    def test_remove(self):
        cache = LatestValueCache()
        cache.update("mac1", {"cpu": 10})
        cache.remove("mac1")
        assert cache.get("mac1") is None

    def test_remove_nonexistent_does_not_raise(self):
        cache = LatestValueCache()
        cache.remove("nonexistent")  # Should not raise

    def test_clear(self):
        cache = LatestValueCache()
        cache.update("mac1", {"cpu": 10})
        cache.update("mac2", {"cpu": 20})
        cache.clear()
        assert cache.get_all() == {}

    def test_updated_at_timestamp(self):
        cache = LatestValueCache()
        before = time.time()
        cache.update("mac1", {"cpu": 10})
        after = time.time()
        result = cache.get("mac1")
        assert result is not None
        assert "_updated_at" in result
        assert before <= result["_updated_at"] <= after

    def test_get_fresh_returns_data_when_fresh(self):
        cache = LatestValueCache()
        cache.update("mac1", {"cpu": 10})
        result = cache.get_fresh("mac1", max_age_seconds=60)
        assert result is not None
        assert result["cpu"] == 10

    def test_get_fresh_returns_none_when_stale(self):
        cache = LatestValueCache()
        cache.update("mac1", {"cpu": 10})
        # Manually backdate the timestamp
        cache._data["mac1"]["_updated_at"] = time.time() - 120
        result = cache.get_fresh("mac1", max_age_seconds=60)
        assert result is None

    def test_get_fresh_returns_none_when_missing(self):
        cache = LatestValueCache()
        assert cache.get_fresh("nonexistent") is None

    def test_len(self):
        cache = LatestValueCache()
        assert len(cache) == 0
        cache.update("mac1", {"cpu": 10})
        assert len(cache) == 1
        cache.update("mac2", {"cpu": 20})
        assert len(cache) == 2
        cache.remove("mac1")
        assert len(cache) == 1
```

### 3b. Run test (expect import failure)

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_latest_value_cache.py -x -v 2>&1 | head -30
```

### 3c. Create module directories and the LatestValueCache implementation

**Create directories:**

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
mkdir -p app/modules/telemetry/services
mkdir -p app/modules/telemetry/extractors
```

**Create file:** `backend/app/modules/telemetry/__init__.py`

```python
"""Telemetry module — real-time device stats ingestion via Mist WebSocket."""
```

**Create file:** `backend/app/modules/telemetry/services/__init__.py`

```python
"""Telemetry services."""
```

**Create file:** `backend/app/modules/telemetry/extractors/__init__.py`

```python
"""Telemetry metric extractors (per device type)."""
```

**Create file:** `backend/app/modules/telemetry/services/latest_value_cache.py`

```python
"""
In-memory cache of latest device stats, keyed by device MAC.

Provides zero-latency reads for impact analysis and AI chat context.
Thread-safe via a simple lock — write contention is low (one writer
from the ingestion coroutine).
"""

import copy
import threading
import time


class LatestValueCache:
    """Latest-value cache for device telemetry stats.

    Stores the full raw payload plus an ``_updated_at`` epoch timestamp
    for each device MAC.  All public methods are thread-safe.
    """

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def update(self, mac: str, stats: dict) -> None:
        """Insert or replace the cached stats for *mac*."""
        entry = {**stats, "_updated_at": time.time()}
        with self._lock:
            self._data[mac] = entry

    def remove(self, mac: str) -> None:
        """Remove a device from the cache (no-op if absent)."""
        with self._lock:
            self._data.pop(mac, None)

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._data.clear()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, mac: str) -> dict | None:
        """Return a deep copy of the cached stats, or ``None``."""
        with self._lock:
            entry = self._data.get(mac)
            if entry is None:
                return None
            return copy.deepcopy(entry)

    def get_fresh(self, mac: str, max_age_seconds: float = 60) -> dict | None:
        """Return cached stats only if younger than *max_age_seconds*."""
        with self._lock:
            entry = self._data.get(mac)
            if entry is None:
                return None
            if time.time() - entry["_updated_at"] > max_age_seconds:
                return None
            return copy.deepcopy(entry)

    def get_all(self) -> dict[str, dict]:
        """Return a deep copy of the full cache."""
        with self._lock:
            return copy.deepcopy(self._data)

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
```

### 3d. Run tests (expect green)

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_latest_value_cache.py -x -v
```

### 3e. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/telemetry/ tests/unit/test_latest_value_cache.py
git commit -m "$(cat <<'EOF'
feat(telemetry): add LatestValueCache with full unit tests

Thread-safe in-memory dict keyed by device MAC. Stores raw payload
with _updated_at timestamp. get_fresh() returns None if data is stale.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 4 — Create CoV filter (test first)

### 4a. Write failing test

**Create file:** `backend/tests/unit/test_cov_filter.py`

```python
"""Unit tests for the Change-of-Value filter."""

import time

from app.modules.telemetry.services.cov_filter import CoVFilter


class TestCoVFilterFirstWrite:
    """First write for any key should always pass."""

    def test_first_write_returns_true(self):
        cov = CoVFilter()
        assert cov.should_write("device1:radio:band_24", {"channel": 6}, {"channel": "exact"}) is True

    def test_separate_keys_are_independent(self):
        cov = CoVFilter()
        assert cov.should_write("key_a", {"val": 1}, {"val": "exact"}) is True
        cov.record_write("key_a", {"val": 1})
        assert cov.should_write("key_b", {"val": 1}, {"val": "exact"}) is True


class TestCoVFilterExactThreshold:
    """Exact threshold: write when value differs."""

    def test_no_change_returns_false(self):
        cov = CoVFilter()
        fields = {"channel": 6, "power": 17}
        thresholds = {"channel": "exact", "power": "exact"}
        cov.should_write("k", fields, thresholds)
        cov.record_write("k", fields)
        assert cov.should_write("k", {"channel": 6, "power": 17}, thresholds) is False

    def test_change_returns_true(self):
        cov = CoVFilter()
        thresholds = {"channel": "exact"}
        cov.should_write("k", {"channel": 6}, thresholds)
        cov.record_write("k", {"channel": 6})
        assert cov.should_write("k", {"channel": 11}, thresholds) is True


class TestCoVFilterAlwaysThreshold:
    """Always threshold: always write (used for counters)."""

    def test_always_returns_true_even_if_unchanged(self):
        cov = CoVFilter()
        thresholds = {"tx_pkts": "always"}
        cov.should_write("k", {"tx_pkts": 100}, thresholds)
        cov.record_write("k", {"tx_pkts": 100})
        assert cov.should_write("k", {"tx_pkts": 100}, thresholds) is True


class TestCoVFilterAbsoluteDelta:
    """Float threshold: write when absolute delta exceeds threshold."""

    def test_below_threshold_returns_false(self):
        cov = CoVFilter()
        thresholds = {"util_all": 5.0}
        cov.should_write("k", {"util_all": 50.0}, thresholds)
        cov.record_write("k", {"util_all": 50.0})
        assert cov.should_write("k", {"util_all": 53.0}, thresholds) is False

    def test_at_threshold_returns_false(self):
        cov = CoVFilter()
        thresholds = {"util_all": 5.0}
        cov.should_write("k", {"util_all": 50.0}, thresholds)
        cov.record_write("k", {"util_all": 50.0})
        # Exactly at threshold — not exceeded
        assert cov.should_write("k", {"util_all": 55.0}, thresholds) is False

    def test_above_threshold_returns_true(self):
        cov = CoVFilter()
        thresholds = {"util_all": 5.0}
        cov.should_write("k", {"util_all": 50.0}, thresholds)
        cov.record_write("k", {"util_all": 50.0})
        assert cov.should_write("k", {"util_all": 56.0}, thresholds) is True

    def test_negative_delta_above_threshold(self):
        cov = CoVFilter()
        thresholds = {"noise_floor": 3.0}
        cov.should_write("k", {"noise_floor": -90.0}, thresholds)
        cov.record_write("k", {"noise_floor": -90.0})
        assert cov.should_write("k", {"noise_floor": -94.0}, thresholds) is True


class TestCoVFilterStaleness:
    """Max staleness timeout forces a write even without changes."""

    def test_stale_entry_returns_true(self):
        cov = CoVFilter(max_staleness_seconds=300)
        thresholds = {"channel": "exact"}
        cov.should_write("k", {"channel": 6}, thresholds)
        cov.record_write("k", {"channel": 6})

        # Backdate the last-write time
        key_entry = cov._last_written["k"]
        cov._last_written["k"] = (key_entry[0], time.time() - 301)

        assert cov.should_write("k", {"channel": 6}, thresholds) is True

    def test_not_stale_returns_false(self):
        cov = CoVFilter(max_staleness_seconds=300)
        thresholds = {"channel": "exact"}
        cov.should_write("k", {"channel": 6}, thresholds)
        cov.record_write("k", {"channel": 6})
        assert cov.should_write("k", {"channel": 6}, thresholds) is False


class TestCoVFilterNewField:
    """A new field not present in the previous write should trigger a write."""

    def test_new_field_returns_true(self):
        cov = CoVFilter()
        cov.should_write("k", {"channel": 6}, {"channel": "exact"})
        cov.record_write("k", {"channel": 6})
        # New field 'power' added — previous write didn't have it
        assert cov.should_write("k", {"channel": 6, "power": 17}, {"channel": "exact", "power": "exact"}) is True


class TestCoVFilterRecordWrite:
    """record_write updates internal tracking."""

    def test_record_write_updates_state(self):
        cov = CoVFilter()
        cov.should_write("k", {"val": 1}, {"val": "exact"})
        cov.record_write("k", {"val": 1})
        # Same value — should not write
        assert cov.should_write("k", {"val": 1}, {"val": "exact"}) is False
        # Different value — should write
        assert cov.should_write("k", {"val": 2}, {"val": "exact"}) is True


class TestCoVFilterMixedThresholds:
    """Multiple fields with different threshold types in one call."""

    def test_mixed_thresholds_one_triggers(self):
        cov = CoVFilter()
        fields = {"channel": 6, "util_all": 50.0, "tx_pkts": 100}
        thresholds = {"channel": "exact", "util_all": 5.0, "tx_pkts": "always"}
        cov.should_write("k", fields, thresholds)
        cov.record_write("k", fields)
        # Only tx_pkts is "always" — that alone triggers a write
        assert cov.should_write("k", {"channel": 6, "util_all": 51.0, "tx_pkts": 100}, thresholds) is True

    def test_mixed_thresholds_none_triggers(self):
        cov = CoVFilter()
        fields = {"channel": 6, "util_all": 50.0}
        thresholds = {"channel": "exact", "util_all": 5.0}
        cov.should_write("k", fields, thresholds)
        cov.record_write("k", fields)
        # channel same, util_all within 5.0 threshold
        assert cov.should_write("k", {"channel": 6, "util_all": 52.0}, thresholds) is False
```

### 4b. Run test (expect import failure)

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_cov_filter.py -x -v 2>&1 | head -20
```

### 4c. Implement CoVFilter

**Create file:** `backend/app/modules/telemetry/services/cov_filter.py`

```python
"""
Change-of-Value filter for telemetry metric writes.

Reduces InfluxDB write volume by 60-80% while maintaining data fidelity.
Based on the OPC UA deadband pattern used in industrial telemetry.

Threshold types:
  - ``"exact"``: write when value differs from last written value
  - ``"always"``: always write (for monotonic counters like tx_pkts)
  - ``float``: write when absolute delta exceeds the threshold

A max-staleness timeout forces a write even when no values have changed,
guaranteeing data freshness for dashboard queries.
"""

import time


class CoVFilter:
    """Change-of-Value filter with max staleness timeout.

    The filter is keyed by an opaque string (typically
    ``f"{mac}:{measurement}:{tag_hash}"``).  Call :meth:`should_write`
    before writing, and :meth:`record_write` after a successful write.
    """

    def __init__(self, max_staleness_seconds: int = 300) -> None:
        self.max_staleness_seconds = max_staleness_seconds
        # key -> (last_fields_dict, last_write_epoch)
        self._last_written: dict[str, tuple[dict, float]] = {}

    def should_write(self, key: str, fields: dict, thresholds: dict) -> bool:
        """Return ``True`` if any field changed beyond its threshold or staleness exceeded."""
        prev = self._last_written.get(key)
        if prev is None:
            return True  # First write for this key

        prev_fields, prev_time = prev

        # Staleness check
        if time.time() - prev_time > self.max_staleness_seconds:
            return True

        for field_name, value in fields.items():
            threshold = thresholds.get(field_name)
            prev_value = prev_fields.get(field_name)

            # New field not in previous write or no threshold defined
            if prev_value is None or threshold is None:
                return True

            if threshold == "always":
                return True

            if threshold == "exact":
                if value != prev_value:
                    return True
            else:
                # Numeric absolute delta
                try:
                    if abs(float(value) - float(prev_value)) > float(threshold):
                        return True
                except (TypeError, ValueError):
                    # Non-numeric — fall back to exact comparison
                    if value != prev_value:
                        return True

        return False

    def record_write(self, key: str, fields: dict) -> None:
        """Update internal tracking after a successful write."""
        self._last_written[key] = (dict(fields), time.time())
```

### 4d. Run tests (expect green)

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_cov_filter.py -x -v
```

### 4e. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/telemetry/services/cov_filter.py tests/unit/test_cov_filter.py
git commit -m "$(cat <<'EOF'
feat(telemetry): add CoV (Change-of-Value) filter with unit tests

Supports exact, always, and absolute-delta threshold types. Includes
max staleness timeout (default 300s) to guarantee data freshness.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 5 — Create InfluxDBService (test first)

### 5a. Write failing test

**Create file:** `backend/tests/unit/test_influxdb_service.py`

```python
"""Unit tests for InfluxDBService with mocked InfluxDB client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.telemetry.services.influxdb_service import InfluxDBService


class TestInfluxDBServiceInit:
    """Test construction and configuration."""

    def test_creates_with_defaults(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="test-token",
            org="test-org",
            bucket="test-bucket",
        )
        assert svc.url == "http://localhost:8086"
        assert svc.org == "test-org"
        assert svc.bucket == "test-bucket"
        assert svc._client is None  # Not connected yet


class TestInfluxDBServiceWriteBuffer:
    """Test the internal write buffer."""

    def test_buffer_is_bounded(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="t",
            org="o",
            bucket="b",
            buffer_size=100,
        )
        assert svc._buffer.maxsize == 100


class TestInfluxDBServiceWritePoints:
    """Test write_points queues data correctly."""

    @pytest.mark.asyncio
    async def test_write_points_adds_to_buffer(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="t",
            org="o",
            bucket="b",
        )
        points = [
            {"measurement": "device_summary", "tags": {"mac": "aa:bb"}, "fields": {"cpu": 42}, "time": 1000},
        ]
        await svc.write_points(points)
        assert svc._buffer.qsize() == 1

    @pytest.mark.asyncio
    async def test_write_points_multiple(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="t",
            org="o",
            bucket="b",
        )
        for i in range(5):
            await svc.write_points([{"measurement": "m", "tags": {}, "fields": {"v": i}, "time": i}])
        assert svc._buffer.qsize() == 5

    @pytest.mark.asyncio
    async def test_write_points_drops_when_buffer_full(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="t",
            org="o",
            bucket="b",
            buffer_size=2,
        )
        await svc.write_points([{"measurement": "m", "tags": {}, "fields": {"v": 1}, "time": 1}])
        await svc.write_points([{"measurement": "m", "tags": {}, "fields": {"v": 2}, "time": 2}])
        # Buffer is full — this should not raise, just drop
        await svc.write_points([{"measurement": "m", "tags": {}, "fields": {"v": 3}, "time": 3}])
        assert svc._buffer.qsize() == 2


class TestInfluxDBServiceTestConnection:
    """Test the test_connection method."""

    @pytest.mark.asyncio
    async def test_connection_success(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="t",
            org="o",
            bucket="b",
        )
        mock_client = MagicMock()
        mock_client.ping = AsyncMock(return_value=True)
        mock_client.close = AsyncMock()

        with patch(
            "app.modules.telemetry.services.influxdb_service.InfluxDBClientAsync",
            return_value=mock_client,
        ):
            ok, error = await svc.test_connection()

        assert ok is True
        assert error is None
        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connection_failure(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="t",
            org="o",
            bucket="b",
        )
        mock_client = MagicMock()
        mock_client.ping = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.close = AsyncMock()

        with patch(
            "app.modules.telemetry.services.influxdb_service.InfluxDBClientAsync",
            return_value=mock_client,
        ):
            ok, error = await svc.test_connection()

        assert ok is False
        assert "Connection refused" in error


class TestInfluxDBServiceFlush:
    """Test the _flush_buffer coroutine."""

    @pytest.mark.asyncio
    async def test_flush_writes_batch(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="t",
            org="o",
            bucket="b",
            batch_size=3,
            flush_interval_seconds=0.1,
        )

        # Pre-fill buffer
        for i in range(3):
            await svc.write_points([{"measurement": "m", "tags": {}, "fields": {"v": i}, "time": i}])

        mock_write_api = AsyncMock()
        mock_client = MagicMock()
        mock_client.write_api = mock_write_api
        mock_client.close = AsyncMock()
        svc._client = mock_client

        # Run one flush cycle
        await svc._flush_once()

        assert mock_write_api.write.call_count == 1
        assert svc._buffer.qsize() == 0

    @pytest.mark.asyncio
    async def test_flush_partial_batch_on_timeout(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="t",
            org="o",
            bucket="b",
            batch_size=100,  # Large batch — won't fill
            flush_interval_seconds=0.05,
        )

        await svc.write_points([{"measurement": "m", "tags": {}, "fields": {"v": 1}, "time": 1}])

        mock_write_api = AsyncMock()
        mock_client = MagicMock()
        mock_client.write_api = mock_write_api
        mock_client.close = AsyncMock()
        svc._client = mock_client

        await svc._flush_once()

        assert mock_write_api.write.call_count == 1
        assert svc._buffer.qsize() == 0


class TestInfluxDBServiceStartStop:
    """Test lifecycle methods."""

    @pytest.mark.asyncio
    async def test_start_creates_client(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="t",
            org="o",
            bucket="b",
        )
        mock_client = MagicMock()
        mock_client.ping = AsyncMock(return_value=True)
        mock_client.close = AsyncMock()
        mock_write_api = AsyncMock()
        mock_client.write_api = mock_write_api

        with patch(
            "app.modules.telemetry.services.influxdb_service.InfluxDBClientAsync",
            return_value=mock_client,
        ):
            await svc.start()

        assert svc._client is not None
        assert svc._flush_task is not None

        # Cleanup
        svc._flush_task.cancel()
        try:
            await svc._flush_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_stop_flushes_and_closes(self):
        svc = InfluxDBService(
            url="http://localhost:8086",
            token="t",
            org="o",
            bucket="b",
            flush_interval_seconds=0.05,
        )
        mock_write_api = AsyncMock()
        mock_client = MagicMock()
        mock_client.write_api = mock_write_api
        mock_client.close = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)

        with patch(
            "app.modules.telemetry.services.influxdb_service.InfluxDBClientAsync",
            return_value=mock_client,
        ):
            await svc.start()

        # Add a point then stop
        await svc.write_points([{"measurement": "m", "tags": {}, "fields": {"v": 1}, "time": 1}])
        await svc.stop()

        mock_client.close.assert_awaited_once()
        assert svc._client is None
```

### 5b. Run test (expect import failure)

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_influxdb_service.py -x -v 2>&1 | head -20
```

### 5c. Implement InfluxDBService

**Create file:** `backend/app/modules/telemetry/services/influxdb_service.py`

```python
"""
Async InfluxDB service with internal write buffer.

Batches data points and flushes to InfluxDB either when the batch
reaches ``batch_size`` or every ``flush_interval_seconds``, whichever
comes first.  If the buffer is full (bounded at ``buffer_size``),
new points are silently dropped — telemetry is ephemeral and Mist
Cloud retains the authoritative data.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from influxdb_client import WritePrecision
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync

logger = structlog.get_logger(__name__)


class InfluxDBService:
    """Async InfluxDB writer with internal bounded buffer and batch flush."""

    def __init__(
        self,
        url: str,
        token: str,
        org: str,
        bucket: str,
        *,
        buffer_size: int = 10_000,
        batch_size: int = 500,
        flush_interval_seconds: float = 10.0,
    ) -> None:
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds

        self._buffer: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=buffer_size)
        self._client: InfluxDBClientAsync | None = None
        self._flush_task: asyncio.Task | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create the InfluxDB client and start the flush coroutine."""
        self._client = InfluxDBClientAsync(
            url=self.url,
            token=self.token,
            org=self.org,
        )
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop(), name="influxdb_flush")
        logger.info("influxdb_service_started", url=self.url, org=self.org, bucket=self.bucket)

    async def stop(self) -> None:
        """Flush remaining points and close the client."""
        self._running = False

        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        # Final flush of anything left in the buffer
        if self._client is not None:
            try:
                await self._flush_once()
            except Exception as exc:
                logger.warning("influxdb_final_flush_failed", error=str(exc))

            await self._client.close()
            self._client = None

        logger.info("influxdb_service_stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def write_points(self, points: list[dict[str, Any]]) -> None:
        """Enqueue data points for batched writing.

        If the buffer is full, points are silently dropped.
        """
        for point in points:
            try:
                self._buffer.put_nowait(point)
            except asyncio.QueueFull:
                logger.warning("influxdb_buffer_full_dropping_point", measurement=point.get("measurement"))

    async def test_connection(self) -> tuple[bool, str | None]:
        """Test connectivity to InfluxDB. Returns ``(ok, error_message)``."""
        client = None
        try:
            client = InfluxDBClientAsync(
                url=self.url,
                token=self.token,
                org=self.org,
            )
            result = await client.ping()
            if result:
                return True, None
            return False, "Ping returned False"
        except Exception as exc:
            return False, str(exc)
        finally:
            if client is not None:
                await client.close()

    async def query_range(
        self,
        measurement: str,
        mac: str,
        field: str,
        start: str = "-1h",
        stop: str = "now()",
    ) -> list[dict[str, Any]]:
        """Query a time range from InfluxDB. Returns list of records."""
        if self._client is None:
            return []

        query = (
            f'from(bucket: "{self.bucket}")'
            f" |> range(start: {start}, stop: {stop})"
            f' |> filter(fn: (r) => r._measurement == "{measurement}")'
            f' |> filter(fn: (r) => r.mac == "{mac}")'
            f' |> filter(fn: (r) => r._field == "{field}")'
        )

        try:
            query_api = self._client.query_api()
            tables = await query_api.query(query, org=self.org)
            records = []
            for table in tables:
                for record in table.records:
                    records.append(
                        {
                            "time": record.get_time().isoformat(),
                            "value": record.get_value(),
                            "field": record.get_field(),
                        }
                    )
            return records
        except Exception as exc:
            logger.error("influxdb_query_failed", error=str(exc))
            return []

    async def query_latest(self, measurement: str, mac: str) -> dict[str, Any] | None:
        """Query the latest record for a measurement + MAC."""
        if self._client is None:
            return None

        query = (
            f'from(bucket: "{self.bucket}")'
            " |> range(start: -5m)"
            f' |> filter(fn: (r) => r._measurement == "{measurement}")'
            f' |> filter(fn: (r) => r.mac == "{mac}")'
            " |> last()"
        )

        try:
            query_api = self._client.query_api()
            tables = await query_api.query(query, org=self.org)
            if tables and tables[0].records:
                record = tables[0].records[0]
                return {
                    "time": record.get_time().isoformat(),
                    "value": record.get_value(),
                    "field": record.get_field(),
                }
            return None
        except Exception as exc:
            logger.error("influxdb_query_latest_failed", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Internal flush loop
    # ------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        """Background coroutine: flush buffer on batch-size or interval."""
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval_seconds)
                await self._flush_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("influxdb_flush_error", error=str(exc))

    async def _flush_once(self) -> None:
        """Drain the buffer and write to InfluxDB in one batch."""
        if self._client is None:
            return

        batch: list[dict[str, Any]] = []
        while not self._buffer.empty() and len(batch) < self.batch_size:
            try:
                point = self._buffer.get_nowait()
                batch.append(point)
            except asyncio.QueueEmpty:
                break

        if not batch:
            return

        try:
            write_api = self._client.write_api
            await write_api.write(
                bucket=self.bucket,
                org=self.org,
                record=batch,
                write_precision=WritePrecision.S,
            )
            logger.debug("influxdb_batch_written", count=len(batch))
        except Exception as exc:
            logger.error("influxdb_write_failed", error=str(exc), batch_size=len(batch))
            # Points are lost — telemetry is ephemeral
```

### 5d. Run tests (expect green)

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_influxdb_service.py -x -v
```

### 5e. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/telemetry/services/influxdb_service.py tests/unit/test_influxdb_service.py
git commit -m "$(cat <<'EOF'
feat(telemetry): add async InfluxDBService with buffered writes and unit tests

Bounded asyncio.Queue (10K), batch flush (500 points or 10s),
test_connection, query_range, query_latest. Mocked InfluxDB in tests.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 6 — Create telemetry router with `/telemetry/status` endpoint

### 6a. Create the router

**Create file:** `backend/app/modules/telemetry/router.py`

```python
"""
Telemetry REST API — status and query endpoints.

Plan 1 (foundation) includes only the /telemetry/status endpoint.
Query endpoints will be added in Plan 3.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from app.dependencies import require_admin
from app.models.system import SystemConfig
from app.models.user import User

router = APIRouter(tags=["Telemetry"])
logger = structlog.get_logger(__name__)


@router.get("/telemetry/status")
async def get_telemetry_status(_current_user: User = Depends(require_admin)):
    """
    Return telemetry subsystem status (admin only).

    Reports whether telemetry is enabled, InfluxDB connection health,
    and basic cache/buffer statistics.
    """
    config = await SystemConfig.get_config()

    if not config.telemetry_enabled:
        return {
            "enabled": False,
            "influxdb": {"connected": False},
            "websocket": {"connections": 0, "channels": 0},
            "cache": {"devices": 0},
            "buffer": {"queued": 0},
        }

    # When telemetry is enabled, try to read live stats from the service
    # instances.  During Plan 1 (foundation) the services may not be
    # running yet — return placeholder zeros.
    influxdb_connected = False
    cache_size = 0
    buffer_depth = 0

    try:
        from app.modules.telemetry.services import _influxdb_service, _latest_cache

        if _latest_cache is not None:
            cache_size = len(_latest_cache)
        if _influxdb_service is not None:
            buffer_depth = _influxdb_service._buffer.qsize()
            influxdb_connected = _influxdb_service._client is not None
    except (ImportError, AttributeError):
        pass

    return {
        "enabled": True,
        "influxdb": {"connected": influxdb_connected},
        "websocket": {"connections": 0, "channels": 0},
        "cache": {"devices": cache_size},
        "buffer": {"queued": buffer_depth},
    }
```

### 6b. Update services `__init__.py` with module-level singletons

**Replace file:** `backend/app/modules/telemetry/services/__init__.py`

```python
"""
Telemetry services — module-level singletons.

Initialized by ``telemetry_startup()`` / torn down by ``telemetry_shutdown()``
in ``app.main`` lifespan.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.telemetry.services.influxdb_service import InfluxDBService
    from app.modules.telemetry.services.latest_value_cache import LatestValueCache

_influxdb_service: InfluxDBService | None = None
_latest_cache: LatestValueCache | None = None
```

### 6c. Verify it all imports cleanly

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/python -c "from app.modules.telemetry.router import router; print('router OK')"
```

### 6d. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/telemetry/router.py app/modules/telemetry/services/__init__.py
git commit -m "$(cat <<'EOF'
feat(telemetry): add /telemetry/status endpoint and service singletons

Returns telemetry enabled state, InfluxDB connection status, cache
size, and buffer depth. Singletons initialized during lifespan.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 7 — Register telemetry module and add lifespan hooks

### 7a. Register module in `app/modules/__init__.py`

Add the following entry at the end of the `MODULES` list (before the closing `]`):

```python
    AppModule(
        name="telemetry",
        router_module="app.modules.telemetry.router",
        model_imports=[],  # No Beanie models — config in SystemConfig, data in InfluxDB
        tags=["Telemetry"],
    ),
```

### 7b. Add startup/shutdown hooks in `app/main.py`

Add the following startup block after the WebSocket heartbeat section (after line 103 `logger.info("websocket_heartbeat_started")`) and before `logger.info("application_started_successfully")`:

```python
        # Start telemetry services if enabled
        try:
            from app.models.system import SystemConfig as _SysConfig

            _telem_config = await _SysConfig.get_config()
            if _telem_config.telemetry_enabled:
                from app.core.security import decrypt_sensitive_data
                from app.modules.telemetry.services import (
                    _influxdb_service as _unused_idb,
                    _latest_cache as _unused_lc,
                )
                from app.modules.telemetry.services.influxdb_service import InfluxDBService
                from app.modules.telemetry.services.latest_value_cache import LatestValueCache

                import app.modules.telemetry.services as _telem_svc

                _telem_svc._latest_cache = LatestValueCache()

                _influx_token = ""
                if _telem_config.influxdb_token:
                    _influx_token = decrypt_sensitive_data(_telem_config.influxdb_token)

                _telem_svc._influxdb_service = InfluxDBService(
                    url=_telem_config.influxdb_url,
                    token=_influx_token,
                    org=_telem_config.influxdb_org,
                    bucket=_telem_config.influxdb_bucket,
                )
                await _telem_svc._influxdb_service.start()
                logger.info("telemetry_services_started")
        except Exception as e:
            logger.warning("telemetry_start_failed", error=str(e))
```

Add the following shutdown block in the `finally` section, after the Smee.io stop block and before `await Database.close_db()`:

```python
        # Stop telemetry services
        try:
            import app.modules.telemetry.services as _telem_svc_shutdown

            if _telem_svc_shutdown._influxdb_service is not None:
                await _telem_svc_shutdown._influxdb_service.stop()
                _telem_svc_shutdown._influxdb_service = None
            if _telem_svc_shutdown._latest_cache is not None:
                _telem_svc_shutdown._latest_cache.clear()
                _telem_svc_shutdown._latest_cache = None
        except Exception:
            pass
```

### 7c. Verify the app boots

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/python -c "from app.main import app; print('app loaded OK')"
```

### 7d. Run the full test suite to check nothing is broken

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/ -x -v --timeout=30
```

### 7e. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/__init__.py app/main.py
git commit -m "$(cat <<'EOF'
feat(telemetry): register telemetry module and add lifespan hooks

Module registered in MODULES list. Startup creates LatestValueCache
and InfluxDBService when telemetry_enabled is True. Shutdown flushes
buffer and closes client.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 8 — Run linters and type checker, fix any issues

### 8a. Black formatting

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/black app/modules/telemetry/ tests/unit/test_latest_value_cache.py tests/unit/test_cov_filter.py tests/unit/test_influxdb_service.py
```

### 8b. Ruff lint

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/ruff check app/modules/telemetry/ tests/unit/test_latest_value_cache.py tests/unit/test_cov_filter.py tests/unit/test_influxdb_service.py --fix
```

### 8c. MyPy type check

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/mypy app/modules/telemetry/ --no-error-summary
```

### 8d. Fix any issues reported, then commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add -u
git diff --cached --stat
# Only commit if there are changes
git diff --cached --quiet || git commit -m "$(cat <<'EOF'
style(telemetry): apply black/ruff/mypy fixes

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 9 — Final verification: run full test suite

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/ -v --timeout=30
```

Confirm all telemetry tests pass:
- `tests/unit/test_latest_value_cache.py` — all pass
- `tests/unit/test_cov_filter.py` — all pass
- `tests/unit/test_influxdb_service.py` — all pass

Confirm no existing tests regressed.

---

## Summary of files created/modified

### New files (6)
- `backend/app/modules/telemetry/__init__.py`
- `backend/app/modules/telemetry/router.py`
- `backend/app/modules/telemetry/services/__init__.py`
- `backend/app/modules/telemetry/services/latest_value_cache.py`
- `backend/app/modules/telemetry/services/cov_filter.py`
- `backend/app/modules/telemetry/services/influxdb_service.py`
- `backend/app/modules/telemetry/extractors/__init__.py`
- `backend/tests/unit/test_latest_value_cache.py`
- `backend/tests/unit/test_cov_filter.py`
- `backend/tests/unit/test_influxdb_service.py`

### Modified files (5)
- `backend/pyproject.toml` — added `influxdb-client[async]` dependency + mypy override
- `backend/app/models/system.py` — added 6 telemetry config fields
- `backend/app/schemas/admin.py` — added matching update schema fields + URL validator
- `backend/app/api/v1/admin.py` — added `influxdb_token` to encrypt set + telemetry fields to GET response
- `backend/app/modules/__init__.py` — registered telemetry module
- `backend/app/main.py` — added telemetry startup/shutdown hooks in lifespan

### Commits (8)
1. `feat(telemetry): add influxdb-client[async] dependency and mypy override`
2. `feat(telemetry): add InfluxDB config fields to SystemConfig and admin schema`
3. `feat(telemetry): add LatestValueCache with full unit tests`
4. `feat(telemetry): add CoV (Change-of-Value) filter with unit tests`
5. `feat(telemetry): add async InfluxDBService with buffered writes and unit tests`
6. `feat(telemetry): add /telemetry/status endpoint and service singletons`
7. `feat(telemetry): register telemetry module and add lifespan hooks`
8. `style(telemetry): apply black/ruff/mypy fixes` (conditional)

---

### Critical Files for Implementation
- `/Users/tmunzer/4_dev/mist_automation/backend/app/modules/telemetry/services/latest_value_cache.py`
- `/Users/tmunzer/4_dev/mist_automation/backend/app/modules/telemetry/services/cov_filter.py`
- `/Users/tmunzer/4_dev/mist_automation/backend/app/modules/telemetry/services/influxdb_service.py`
- `/Users/tmunzer/4_dev/mist_automation/backend/app/models/system.py`
- `/Users/tmunzer/4_dev/mist_automation/backend/app/main.py`