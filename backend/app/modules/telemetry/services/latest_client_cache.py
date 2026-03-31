"""In-memory cache of latest wireless client stats per MAC address.

Extends LatestValueCache with client-specific aggregate methods (site summary).
"""

from __future__ import annotations

import time

from app.modules.telemetry.services.latest_value_cache import LatestValueCache


class LatestClientCache(LatestValueCache):
    """Stores the most recent client stats payload per client MAC.

    Inherits all LatestValueCache methods (update, get, get_all_for_site, prune, etc.)
    and adds get_site_summary() for aggregate client KPIs.
    """

    def get_site_summary(self, site_id: str, max_age_seconds: float = 120) -> dict:
        """Compute aggregate client stats for a site from the in-memory cache.

        Returns:
            dict with keys: total_clients, avg_rssi, band_counts, total_tx_bps, total_rx_bps
        """
        now = time.time()
        clients = []
        for _mac, entry in self._entries.items():
            if now - entry["updated_at"] > max_age_seconds:
                continue
            stats = entry.get("stats", {})
            if stats.get("site_id") == site_id:
                clients.append(stats)

        if not clients:
            return {
                "total_clients": 0,
                "avg_rssi": 0.0,
                "band_counts": {},
                "total_tx_bps": 0,
                "total_rx_bps": 0,
            }

        rssiz = [float(c["rssi"]) for c in clients if c.get("rssi") is not None]
        band_counts: dict[str, int] = {}
        proto_counts: dict[str, int] = {}
        channel_counts: dict[str, int] = {}
        auth_counts: dict[str, int] = {}
        for c in clients:
            band = str(c.get("band") or "")
            if band:
                band_counts[band] = band_counts.get(band, 0) + 1
            proto = str(c.get("proto") or "")
            if proto:
                proto_counts[proto] = proto_counts.get(proto, 0) + 1
            channel = c.get("channel")
            if channel is not None:
                ch_key = str(int(channel))
                channel_counts[ch_key] = channel_counts.get(ch_key, 0) + 1
            auth = "eap" if "EAP" in (c.get("key_mgmt") or "").upper() else "psk"
            auth_counts[auth] = auth_counts.get(auth, 0) + 1

        return {
            "total_clients": len(clients),
            "avg_rssi": round(sum(rssiz) / len(rssiz), 1) if rssiz else 0.0,
            "band_counts": band_counts,
            "proto_counts": proto_counts,
            "channel_counts": channel_counts,
            "auth_counts": auth_counts,
            "total_tx_bps": sum(int(c.get("tx_bps") or 0) for c in clients),
            "total_rx_bps": sum(int(c.get("rx_bps") or 0) for c in clients),
        }
