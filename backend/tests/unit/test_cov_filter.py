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
        assert cov.should_write("k", {"util_all": 55.0}, thresholds) is False

    def test_above_threshold_returns_true(self):
        cov = CoVFilter()
        thresholds = {"util_all": 5.0}
        cov.should_write("k", {"util_all": 50.0}, thresholds)
        cov.record_write("k", {"util_all": 50.0})
        assert cov.should_write("k", {"util_all": 55.1}, thresholds) is True

    def test_negative_delta_above_threshold_returns_true(self):
        cov = CoVFilter()
        thresholds = {"util_all": 5.0}
        cov.should_write("k", {"util_all": 50.0}, thresholds)
        cov.record_write("k", {"util_all": 50.0})
        assert cov.should_write("k", {"util_all": 44.0}, thresholds) is True


class TestCoVFilterStaleness:
    """Max staleness: force write even if unchanged after timeout."""

    def test_stale_entry_returns_true(self):
        cov = CoVFilter(max_staleness_seconds=60)
        fields = {"channel": 6}
        thresholds = {"channel": "exact"}
        cov.should_write("k", fields, thresholds)
        cov.record_write("k", fields)
        # Manually backdate
        cov._last_written["k"] = (fields, time.time() - 120)
        assert cov.should_write("k", {"channel": 6}, thresholds) is True

    def test_fresh_entry_unchanged_returns_false(self):
        cov = CoVFilter(max_staleness_seconds=300)
        fields = {"channel": 6}
        thresholds = {"channel": "exact"}
        cov.should_write("k", fields, thresholds)
        cov.record_write("k", fields)
        assert cov.should_write("k", {"channel": 6}, thresholds) is False


class TestCoVFilterNewField:
    """New field not seen before triggers write."""

    def test_new_field_returns_true(self):
        cov = CoVFilter()
        thresholds = {"a": "exact", "b": "exact"}
        cov.should_write("k", {"a": 1}, thresholds)
        cov.record_write("k", {"a": 1})
        # Now add field "b" that wasn't in previous write
        assert cov.should_write("k", {"a": 1, "b": 2}, thresholds) is True


class TestCoVFilterRecordWrite:
    """record_write updates tracking state."""

    def test_record_write_updates_timestamp(self):
        cov = CoVFilter()
        before = time.time()
        cov.record_write("k", {"v": 1})
        after = time.time()
        _, ts = cov._last_written["k"]
        assert before <= ts <= after
