from unittest.mock import AsyncMock, patch

from app.modules.power_scheduling.services.rrm_service import fetch_rf_neighbor_map, merge_rrm_responses


class TestMergeRrmResponses:
    def test_merge_best_rssi_across_bands(self):
        band5 = {"results": [{"mac": "aa", "neighbors": [{"mac": "bb", "rssi": -60.0}]}]}
        band24 = {"results": [{"mac": "aa", "neighbors": [{"mac": "bb", "rssi": -55.0}]}]}
        result = merge_rrm_responses([band5, band24])
        # Should keep best (highest) RSSI: -55
        assert result["aa"] == [("bb", -55)]

    def test_merge_multiple_neighbors(self):
        band5 = {
            "results": [
                {
                    "mac": "aa",
                    "neighbors": [{"mac": "bb", "rssi": -49.0}, {"mac": "cc", "rssi": -66.0}],
                },
            ]
        }
        result = merge_rrm_responses([band5])
        assert ("bb", -49) in result["aa"]
        assert ("cc", -66) in result["aa"]

    def test_missing_results_key(self):
        result = merge_rrm_responses([{}])
        assert result == {}

    def test_empty_neighbors(self):
        band5 = {"results": [{"mac": "aa", "neighbors": []}]}
        result = merge_rrm_responses([band5])
        assert result == {"aa": []}


class TestFetchRfNeighborMap:
    async def test_calls_all_three_bands(self):
        mock_mist = AsyncMock()
        mock_mist.api_get = AsyncMock(return_value={"results": []})
        with patch(
            "app.modules.power_scheduling.services.rrm_service.create_mist_service",
            new_callable=AsyncMock,
            return_value=mock_mist,
        ):
            await fetch_rf_neighbor_map("site-1")
        assert mock_mist.api_get.call_count == 3
        calls = [c.args[0] for c in mock_mist.api_get.call_args_list]
        assert any("24" in c for c in calls)
        assert any("/5" in c for c in calls)
        assert any("/6" in c for c in calls)
