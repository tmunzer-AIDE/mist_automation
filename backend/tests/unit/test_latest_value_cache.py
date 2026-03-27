"""Unit tests for LatestValueCache."""

import time

from app.modules.telemetry.services.latest_value_cache import LatestValueCache


class TestLatestValueCache:
    """Tests for the in-memory latest-value cache."""

    def test_update_and_get(self):
        cache = LatestValueCache()
        cache.update("aabbccddeeff", {"cpu_util": 42, "mem_usage": 65})
        result = cache.get("aabbccddeeff")
        assert result is not None
        assert result["cpu_util"] == 42
        assert result["mem_usage"] == 65

    def test_get_nonexistent_returns_none(self):
        cache = LatestValueCache()
        assert cache.get("000000000000") is None

    def test_update_overwrites_previous(self):
        cache = LatestValueCache()
        cache.update("aabbccddeeff", {"cpu_util": 42})
        cache.update("aabbccddeeff", {"cpu_util": 99, "uptime": 3600})
        result = cache.get("aabbccddeeff")
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
        entry = cache._entries.get("mac1")
        assert entry is not None
        assert before <= entry["updated_at"] <= after

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
        cache._entries["mac1"]["updated_at"] = time.time() - 120
        result = cache.get_fresh("mac1", max_age_seconds=60)
        assert result is None

    def test_get_fresh_returns_none_when_missing(self):
        cache = LatestValueCache()
        assert cache.get_fresh("nonexistent", max_age_seconds=60) is None

    def test_size(self):
        cache = LatestValueCache()
        assert cache.size() == 0
        cache.update("mac1", {"cpu": 10})
        cache.update("mac2", {"cpu": 20})
        assert cache.size() == 2
        cache.remove("mac1")
        assert cache.size() == 1
