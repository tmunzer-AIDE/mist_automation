# Mist WebSocket: Switch `if_stat` Counter Staleness

## Summary

The Mist device stats WebSocket stream (`/sites/{site_id}/stats/devices`) sends **two distinct message types** for switches. One type contains stale `if_stat` port counters, the other contains fresh counters. This causes consumers relying on `if_stat` for traffic telemetry to see constant/stale values most of the time.

## Observed Behavior

For the same switch device (`020003902a34`, EX4100-F-12P VC, Junos 23.4R2-S7.7), the WS stream delivers two types of messages:

### Type 1: "Cached" messages (frequent, ~every 30s)

- `_ttl: 600`
- **No `_time` field**
- `if_stat` counters are **frozen** at a past snapshot
- Other fields (`last_seen`, `cpu_stat`, `memory_stat`, `uptime`, `clients`) **do update**

Example `ge-0/0/11.0` counters across 3 consecutive cached messages (30s apart):
```
last_seen=1774642468  tx_pkts=19758  rx_pkts=2570
last_seen=1774642438  tx_pkts=19758  rx_pkts=2570  (identical)
last_seen=1774642408  tx_pkts=19758  rx_pkts=2570  (identical)
```

### Type 2: "Fresh" messages (less frequent)

- `_ttl: 190`
- **Has `_time` field** (e.g., `_time: 1774324764.347`)
- `if_stat` counters are **real/updated**

Example `ge-0/0/11.0` counters in a fresh message:
```
_time=1774324764.347  tx_pkts=85336  rx_pkts=10204  (different from cached!)
```

## Evidence

Captured via Postman WebSocket connection to `wss://api-ws.mist.com/api-ws/v1/stream`, subscribing to `/sites/503e134b-8e33-4e1e-b756-75e9ba73849e/stats/devices`.

### Device: `020003902a34` (US-NY-SWC-01, EX4100-F-12P VC)

**Cached message** (no `_time`, `_ttl=600`), `last_seen: 1774642468`:
```json
"ge-0/0/11.0": {"tx_pkts": 19758, "rx_pkts": 2570, "rx_bytes": 0, "port_id": "ge-0/0/11", "up": true, "tx_bytes": 0}
"ge-0/0/1.0":  {"tx_pkts": 3669,  "rx_pkts": 3500, "rx_bytes": 0, "port_id": "ge-0/0/1",  "up": true, "tx_bytes": 0}
"ge-0/0/4.0":  {"tx_pkts": 2397,  "rx_pkts": 2391, "rx_bytes": 0, "port_id": "ge-0/0/4",  "up": true, "tx_bytes": 0}
"irb.172":     {"tx_pkts": 10953, "rx_pkts": 20399, ...}
```

**Fresh message** (has `_time: 1774324764.347`, `_ttl=190`), same capture session:
```json
"ge-0/0/11.0": {"tx_pkts": 85336,  "rx_pkts": 10204, "rx_bytes": 0, "port_id": "ge-0/0/11", "up": true, "tx_bytes": 0}
"ge-0/0/1.0":  {"tx_pkts": 34186,  "rx_pkts": 15176, "rx_bytes": 0, "port_id": "ge-0/0/1",  "up": true, "tx_bytes": 0}
"ge-0/0/4.0":  {"tx_pkts": 13919,  "rx_pkts": 13048, "rx_bytes": 0, "port_id": "ge-0/0/4",  "up": true, "tx_bytes": 0}
"irb.172":     {"tx_pkts": 84010,  "rx_pkts": 121570, ...}
```

### Same pattern on other switches

**Device `485a0deb2380` (US-NY-SWA-01, EX4100-F-12P)**:
- Cached (`_ttl=600`): `ge-0/0/1 tx_pkts=22945, rx_pkts=40991`
- Fresh (`_ttl=190`, `_time: 1774325055.76`): `ge-0/0/1 tx_pkts=89262, rx_pkts=226895`

**Device `485a0dea2e00` (US-NY-SWA-02, EX4100-F-12P)**:
- Cached (`_ttl=600`): `ge-0/0/1 tx_pkts=23694, rx_pkts=40440`
- Fresh (`_ttl=190`, `_time: 1774324826.90`): `ge-0/0/1 tx_pkts=89964, rx_pkts=227588`

## Additional observations

- `rx_bytes` and `tx_bytes` are **always 0** for all switch ports in both message types
- `_time` in fresh messages can be significantly older than `last_seen` (hours/days behind)
- APs do NOT exhibit this issue: AP `port_stat` counters update in every full stats message, and `_time` matches `last_seen`
- Gateway `if_stat` has full byte counters (non-zero `rx_bytes`/`tx_bytes`) but also appears to have stale `_time`

## Impact

Any consumer that processes all WS messages and uses `if_stat` counters for switch port telemetry will see constant values, since the majority of messages (~30s interval) contain the cached/stale snapshot. The fresh messages arrive less frequently and are outnumbered.

## Workaround

Filter switch stats messages: only use `if_stat` counters from messages that have the `_time` field set (the "fresh" type with `_ttl=190`). Skip `if_stat` extraction from messages without `_time` (the "cached" type with `_ttl=600`).

## Questions for Mist engineering

1. Is this dual-message behavior intentional? What determines the refresh frequency of the "fresh" (`_ttl=190`) messages?
2. Why are `rx_bytes` and `tx_bytes` always 0 for switch `if_stat`? Is this expected?
3. Is there a way to request only fresh stats (e.g., a different WS channel or parameter)?
4. What does `_ttl` represent in this context - data validity window in seconds?
