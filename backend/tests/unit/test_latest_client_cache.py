"""Unit tests for LatestClientCache."""

import time

from app.modules.telemetry.services.latest_client_cache import LatestClientCache


def _client(mac: str, site_id: str, band: str = "24", rssi: int = -50,
            tx_bps: int = 100, rx_bps: int = 200) -> dict:
    return {
        "mac": mac,
        "site_id": site_id,
        "band": band,
        "rssi": rssi,
        "tx_bps": tx_bps,
        "rx_bps": rx_bps,
    }


class TestLatestClientCache:
    def test_update_and_get(self):
        cache = LatestClientCache()
        stats = _client("aabbccddeeff", "site1")
        cache.update("aabbccddeeff", stats)
        assert cache.get("aabbccddeeff") == stats

    def test_get_unknown_returns_none(self):
        cache = LatestClientCache()
        assert cache.get("000000000000") is None

    def test_size(self):
        cache = LatestClientCache()
        cache.update("aa", _client("aa", "site1"))
        cache.update("bb", _client("bb", "site1"))
        assert cache.size() == 2

    def test_get_all_for_site_returns_matching(self):
        cache = LatestClientCache()
        cache.update("aa", _client("aa", "site1"))
        cache.update("bb", _client("bb", "site2"))
        results = cache.get_all_for_site("site1")
        assert len(results) == 1
        assert results[0]["mac"] == "aa"

    def test_get_site_summary_counts(self):
        cache = LatestClientCache()
        cache.update("aa", _client("aa", "site1", band="24", rssi=-40, tx_bps=100, rx_bps=50))
        cache.update("bb", _client("bb", "site1", band="5", rssi=-60, tx_bps=200, rx_bps=150))
        cache.update("cc", _client("cc", "site2", band="24", rssi=-30, tx_bps=0, rx_bps=0))

        summary = cache.get_site_summary("site1")
        assert summary["total_clients"] == 2
        assert summary["avg_rssi"] == -50.0
        assert summary["band_counts"] == {"24": 1, "5": 1}
        assert summary["total_tx_bps"] == 300
        assert summary["total_rx_bps"] == 200

    def test_get_site_summary_empty_site(self):
        cache = LatestClientCache()
        summary = cache.get_site_summary("no_such_site")
        assert summary["total_clients"] == 0
        assert summary["avg_rssi"] == 0.0
        assert summary["band_counts"] == {}

    def test_prune_removes_stale(self):
        cache = LatestClientCache()
        cache.update("aa", _client("aa", "site1"))
        # Force stale by manipulating entry timestamp
        cache._entries["aa"]["updated_at"] = time.time() - 700
        cache.prune(max_age_seconds=600)
        assert cache.size() == 0

    def test_get_site_summary_excludes_stale(self):
        cache = LatestClientCache()
        cache.update("aa", _client("aa", "site1"))
        cache._entries["aa"]["updated_at"] = time.time() - 200
        # max_age=120 → stale
        summary = cache.get_site_summary("site1", max_age_seconds=120)
        assert summary["total_clients"] == 0
