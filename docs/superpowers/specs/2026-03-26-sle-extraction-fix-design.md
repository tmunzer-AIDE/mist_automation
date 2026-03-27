# SLE Data Extraction & Snapshot Duration Fix

## Context

The impact analysis SLE pipeline has two bugs:

1. **Wrong value source in `_extract_sle_value`**: The function tries `samples.value[]` first (0-1 scale floats), but the correct SLE score should be computed from `(total - degraded) / total * 100`. The `value` array is not the SLE success rate — it's a different metric. The `duration` field in classifiers should also be ignored.

2. **Snapshot uses 10-minute duration**: `capture_snapshot` requests `duration="10m"`, but Mist computes SLEs on a cron (`*/10 * * * *`). A 10-minute window may return empty or stale data. Should always request 60 minutes with 600-second interval (Mist's default for 1h).

3. **Null handling semantics**: The API returns `null` for time buckets with no data (e.g., no 802.1X authentication occurred). These must be excluded from computation, not treated as 0. A metric with all-null buckets = "no data" (skip), not "100% success".

## Design

### `_extract_sle_value` rewrite

- Unwrap `site_trend` key if present (both baseline and snapshot wrap data this way)
- Navigate to `data["sle"]["samples"]` to get `total[]` and `degraded[]`
- Pair index by index, skip where either value is `null` or not a number
- For each valid pair: `(total - degraded) / total * 100`
- Average all valid pairs = success rate percentage (0-100)
- Return `None` if no valid pairs (all nulls, or missing structure)
- Remove dead code: plain numeric handling, `samples.value[]` path, legacy `value`/`score`/`num_users`/`total` key fallbacks

### `capture_snapshot` fix

Change `duration="10m"` to `duration="1h"` (line 188 of sle_service.py).

### No changes to

- `capture_baseline` — already uses `duration="1h"`
- `compute_delta` — logic is correct (averages snapshot values vs baseline), just gets correct values from fixed `_extract_sle_value`
- `drill_down_device_sle` — unrelated to value extraction
- Frontend — consumes `baseline_value`, `current_value`, `change_percent` which keep the same shape

### Files to modify

| File | Change |
|------|--------|
| `backend/app/modules/impact_analysis/services/sle_service.py` | Rewrite `_extract_sle_value`, change snapshot duration |

### Verification

- Unit test `_extract_sle_value` with real API response format (total/degraded arrays, nulls, all-null, missing structure)
- Unit test `compute_delta` with baseline + snapshots using real response format
- Verify `capture_snapshot` uses `duration="1h"`
