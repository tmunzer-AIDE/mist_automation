"""Unit tests for SLE service value extraction and delta computation."""

from app.modules.impact_analysis.services.sle_service import _extract_sle_value


class TestExtractSleValue:
    """Tests for _extract_sle_value — computes success rate from total/degraded arrays."""

    def test_full_success(self):
        """All buckets have zero degradation → 100% success."""
        data = {
            "sle": {
                "samples": {
                    "total": [931.65, 658.93, 661.63, 811.8],
                    "degraded": [0.0, 0.0, 0.0, 0.0],
                    "value": [0.113, 0.776, 0.107, 0.065],  # should be ignored
                }
            }
        }
        result = _extract_sle_value(data)
        assert result == 100.0

    def test_partial_degradation(self):
        """Some buckets have degradation → success rate < 100%."""
        data = {
            "sle": {
                "samples": {
                    "total": [1000.0, 1000.0],
                    "degraded": [100.0, 200.0],
                    "value": [0.5, 0.5],
                }
            }
        }
        result = _extract_sle_value(data)
        # Bucket 0: (1000-100)/1000 = 90%, Bucket 1: (1000-200)/1000 = 80% → avg = 85%
        assert result == 85.0

    def test_null_buckets_skipped(self):
        """Null values in total/degraded are skipped (no data for that period)."""
        data = {
            "sle": {
                "samples": {
                    "total": [931.65, 658.93, None, None],
                    "degraded": [0.0, 0.0, None, None],
                    "value": [0.113, 0.776, None, None],
                }
            }
        }
        result = _extract_sle_value(data)
        assert result == 100.0

    def test_mismatched_nulls_skipped(self):
        """If total is valid but degraded is null (or vice versa), skip that bucket."""
        data = {
            "sle": {
                "samples": {
                    "total": [1000.0, None, 1000.0],
                    "degraded": [None, 0.0, 100.0],
                    "value": [0.5, 0.5, 0.5],
                }
            }
        }
        result = _extract_sle_value(data)
        # Only bucket 2 is valid: (1000-100)/1000 = 90%
        assert result == 90.0

    def test_all_null_returns_none(self):
        """All-null buckets means no data → return None."""
        data = {
            "sle": {
                "samples": {
                    "total": [None, None, None],
                    "degraded": [None, None, None],
                    "value": [None, None, None],
                }
            }
        }
        result = _extract_sle_value(data)
        assert result is None

    def test_zero_total_bucket_skipped(self):
        """A bucket with total=0 should be skipped (avoid division by zero)."""
        data = {
            "sle": {
                "samples": {
                    "total": [0.0, 1000.0],
                    "degraded": [0.0, 50.0],
                    "value": [0.0, 0.5],
                }
            }
        }
        result = _extract_sle_value(data)
        # Only bucket 1: (1000-50)/1000 = 95%
        assert result == 95.0

    def test_site_trend_wrapper(self):
        """Baseline format wraps response in {"site_trend": ...} — unwrap it."""
        data = {
            "site_trend": {
                "sle": {
                    "samples": {
                        "total": [1000.0, 1000.0],
                        "degraded": [0.0, 0.0],
                        "value": [0.5, 0.5],
                    }
                }
            }
        }
        result = _extract_sle_value(data)
        assert result == 100.0

    def test_none_input(self):
        result = _extract_sle_value(None)
        assert result is None

    def test_missing_sle_key(self):
        result = _extract_sle_value({"other": "data"})
        assert result is None

    def test_missing_samples(self):
        result = _extract_sle_value({"sle": {"name": "throughput"}})
        assert result is None

    def test_empty_arrays(self):
        data = {
            "sle": {
                "samples": {
                    "total": [],
                    "degraded": [],
                    "value": [],
                }
            }
        }
        result = _extract_sle_value(data)
        assert result is None

    def test_real_api_response_switch_throughput(self):
        """Real response from getSiteSleSummaryTrend for switch-throughput."""
        data = {
            "start": 1774570849,
            "end": 1774574449,
            "sle": {
                "name": "switch-throughput",
                "x_label": "seconds",
                "y_label": "Mbps",
                "interval": 600,
                "samples": {
                    "total": [931.65, 658.93335, 661.63336, 811.8, None, None],
                    "degraded": [0.0, 0.0, 0.0, 0.0, None, None],
                    "value": [0.11334425, 0.77672905, 0.107510336, 0.0657685, None, None],
                },
            },
            "classifiers": [],
        }
        result = _extract_sle_value(data)
        assert result == 100.0
