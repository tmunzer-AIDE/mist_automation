"""Async InfluxDB service with batched writes and periodic flush.

Manages an InfluxDB client connection, internal write buffer, and a
background flush coroutine. Points are queued via write_points() and
flushed to InfluxDB either when the batch size is reached or on a
periodic interval.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from influxdb_client.domain.write_precision import WritePrecision

logger = structlog.get_logger(__name__)

# Default buffer and flush settings
_DEFAULT_BUFFER_SIZE = 10_000
_DEFAULT_BATCH_SIZE = 500
_DEFAULT_FLUSH_INTERVAL = 10.0  # seconds


class InfluxDBService:
    """Async InfluxDB service with buffered writes."""

    def __init__(
        self,
        url: str,
        token: str,
        org: str,
        bucket: str,
        buffer_size: int = _DEFAULT_BUFFER_SIZE,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        flush_interval: float = _DEFAULT_FLUSH_INTERVAL,
    ) -> None:
        self.url = url
        self.org = org
        self.bucket = bucket
        self._token = token
        self._batch_size = batch_size
        self._flush_interval = flush_interval

        self._buffer: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=buffer_size)
        self._client: Any | None = None
        self._write_api: Any | None = None
        self._flush_task: asyncio.Task | None = None
        self._running = False

        # Stats
        self._points_written = 0
        self._points_dropped = 0
        self._flush_count = 0
        self._last_flush_at: float = 0
        self._last_error: str | None = None

    async def start(self) -> None:
        """Connect to InfluxDB and start the background flush coroutine."""
        from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync

        self._client = InfluxDBClientAsync(url=self.url, token=self._token, org=self.org)
        self._write_api = self._client.write_api()
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop(), name="influxdb_flush")
        logger.info("influxdb_service_started", url=self.url, org=self.org, bucket=self.bucket)

    async def stop(self) -> None:
        """Flush remaining points and close the connection."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Final flush
        if self._write_api:
            await self._flush()

        if self._client:
            await self._client.close()
            self._client = None
            self._write_api = None

        logger.info("influxdb_service_stopped", points_written=self._points_written)

    async def write_points(self, points: list[dict[str, Any]]) -> None:
        """Queue points for batched writing. Drops if buffer is full."""
        for point in points:
            try:
                self._buffer.put_nowait(point)
            except asyncio.QueueFull:
                self._points_dropped += 1

    _MAX_BATCHES_PER_FLUSH = 50  # prevent tight-loop if ingestion outpaces writes

    async def _flush_loop(self) -> None:
        """Background coroutine: flush buffer periodically, draining all pending batches."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                batches = 0
                while self._buffer.qsize() > 0 and batches < self._MAX_BATCHES_PER_FLUSH:
                    await self._flush()
                    batches += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._last_error = str(e)
                logger.warning("influxdb_flush_error", error=str(e))

    async def _flush(self) -> None:
        """Drain buffer and write to InfluxDB."""
        if not self._write_api:
            return

        points: list[dict[str, Any]] = []
        while not self._buffer.empty() and len(points) < self._batch_size:
            try:
                points.append(self._buffer.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not points:
            return

        try:
            await self._write_api.write(bucket=self.bucket, record=points, write_precision=WritePrecision.S)
            self._points_written += len(points)
            self._flush_count += 1
            self._last_flush_at = time.time()
        except Exception as e:
            self._last_error = str(e)
            logger.warning("influxdb_write_failed", error=str(e), points_lost=len(points))

    async def test_connection(self) -> bool:
        """Test InfluxDB connectivity. Returns True if healthy."""
        if not self._client:
            from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync

            client = InfluxDBClientAsync(url=self.url, token=self._token, org=self.org)
            try:
                return await client.ping()
            finally:
                await client.close()
        return await self._client.ping()

    async def query_range(
        self, mac: str, measurement: str, start: str = "-1h", end: str = "now()"
    ) -> list[dict[str, Any]]:
        """Query time-range data for a single device.

        Args:
            mac: Device MAC (pre-validated, 12 hex chars lowercase).
            measurement: InfluxDB measurement name (pre-validated against allowlist).
            start: Range start (e.g., '-1h', '-30m'). Pre-validated.
            end: Range end (e.g., 'now()'). Pre-validated.

        Returns:
            List of dicts, each representing a pivoted row with _time and field values.
        """
        if not self._client:
            return []

        query = (
            f'from(bucket: "{self.bucket}")'
            f" |> range(start: {start}, stop: {end})"
            f' |> filter(fn: (r) => r._measurement == "{measurement}")'
            f' |> filter(fn: (r) => r.mac == "{mac}")'
            ' |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")'
        )

        try:
            query_api = self._client.query_api()
            tables = await query_api.query(query)
            results: list[dict[str, Any]] = []
            for table in tables:
                for record in table.records:
                    results.append(record.values)
            return results
        except Exception as e:
            self._last_error = str(e)
            logger.warning("influxdb_query_range_error", error=str(e), mac=mac, measurement=measurement)
            return []

    async def query_latest(self, mac: str, measurement: str = "device_summary") -> dict[str, Any] | None:
        """Query the latest data point for a device from InfluxDB.

        Args:
            mac: Device MAC (pre-validated).
            measurement: InfluxDB measurement name (pre-validated).

        Returns:
            A single dict with the latest field values, or None.
        """
        if not self._client:
            return None

        query = (
            f'from(bucket: "{self.bucket}")'
            " |> range(start: -5m)"
            f' |> filter(fn: (r) => r._measurement == "{measurement}")'
            f' |> filter(fn: (r) => r.mac == "{mac}")'
            " |> last()"
            ' |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")'
        )

        try:
            query_api = self._client.query_api()
            tables = await query_api.query(query)
            for table in tables:
                for record in table.records:
                    return dict(record.values)
            return None
        except Exception as e:
            self._last_error = str(e)
            logger.warning("influxdb_query_latest_error", error=str(e), mac=mac)
            return None

    async def query_aggregate(
        self,
        measurement: str,
        field: str,
        agg: str = "mean",
        window: str = "5m",
        start: str = "-1h",
        end: str = "now()",
        site_id: str | None = None,
        org_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query aggregated data across all devices at a site or org.

        Args:
            measurement: InfluxDB measurement name (pre-validated).
            field: Field name to aggregate (pre-validated).
            agg: Aggregation function (pre-validated against allowlist).
            window: Aggregation window (pre-validated, e.g., '5m').
            start: Range start (pre-validated).
            end: Range end (pre-validated).
            site_id: Site UUID (pre-validated, mutually exclusive with org_id).
            org_id: Org UUID for org-wide aggregation (pre-validated, mutually exclusive with site_id).

        Returns:
            List of dicts, each with _time and aggregated _value.
        """
        if not self._client:
            return []

        scope_filter = (
            f' |> filter(fn: (r) => r.site_id == "{site_id}")'
            if site_id
            else f' |> filter(fn: (r) => r.org_id == "{org_id}")'
        )

        query = (
            f'from(bucket: "{self.bucket}")'
            f" |> range(start: {start}, stop: {end})"
            f' |> filter(fn: (r) => r._measurement == "{measurement}")'
            f"{scope_filter}"
            f' |> filter(fn: (r) => r._field == "{field}")'
            f" |> aggregateWindow(every: {window}, fn: {agg}, createEmpty: false)"
        )

        try:
            query_api = self._client.query_api()
            tables = await query_api.query(query)
            results: list[dict[str, Any]] = []
            for table in tables:
                for record in table.records:
                    results.append(record.values)
            return results
        except Exception as e:
            self._last_error = str(e)
            logger.warning(
                "influxdb_query_aggregate_error",
                error=str(e),
                site_id=site_id,
                org_id=org_id,
                measurement=measurement,
                field=field,
            )
            return []

    def get_stats(self) -> dict[str, Any]:
        """Return service statistics."""
        return {
            "connected": self._client is not None and self._running,
            "buffer_size": self._buffer.qsize(),
            "buffer_capacity": self._buffer.maxsize,
            "points_written": self._points_written,
            "points_dropped": self._points_dropped,
            "flush_count": self._flush_count,
            "last_flush_at": self._last_flush_at,
            "last_error": self._last_error,
        }
