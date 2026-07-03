"""LiveDatadogAdapter — read-only access to a real Datadog org via its REST API.

Maps Datadog metric queries and events into the normalized telemetry model so it
is interchangeable with the ReplayAdapter behind the DataSource interface. Only
read endpoints are used. Keys are passed in (from app.config, never hard-coded).

Metric name -> Datadog query mapping is configurable per environment; the
defaults are illustrative golden-signal-style queries (see OPEN-QUESTIONS.md).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from app.telemetry.base import DataSource
from app.telemetry.models import (
    EventSource,
    MetricPoint,
    MetricSeries,
    Severity,
    TelemetryEvent,
)

_DEFAULT_METRIC_QUERIES: dict[str, str] = {
    "api.latency.p95": "p95:trace.http.request.duration{*}",
    "api.error_rate": "sum:trace.http.request.errors{*}.as_rate()",
    "api.requests.rps": "sum:trace.http.request.hits{*}.as_rate()",
    "system.cpu.user": "avg:system.cpu.user{*}",
}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _map_severity(alert_type: str | None) -> Severity:
    return {
        "error": Severity.CRITICAL,
        "warning": Severity.WARNING,
    }.get((alert_type or "").lower(), Severity.INFO)


def _classify_source(event: dict) -> EventSource:
    haystack = (str(event.get("title", "")) + " " + " ".join(event.get("tags", []))).lower()
    if "deploy" in haystack or "rollback" in haystack:
        return EventSource.DEPLOY
    return EventSource.METRIC


class LiveDatadogAdapter(DataSource):
    source_type = "datadog"

    def __init__(
        self,
        api_key: str = "",
        app_key: str = "",
        site: str = "datadoghq.com",
        access_token: str = "",
        metric_queries: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._metric_queries = metric_queries or dict(_DEFAULT_METRIC_QUERIES)
        # A Personal Access Token authenticates on its own (Bearer); fall back to
        # the legacy API-key + Application-key header pair when no token is given.
        if access_token:
            headers = {"Authorization": f"Bearer {access_token}"}
        else:
            headers = {"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key}
        self._client = httpx.Client(
            base_url=f"https://api.{site}",
            headers=headers,
            transport=transport,
            timeout=timeout,
        )

    def list_metrics(self) -> list[str]:
        return list(self._metric_queries.keys())

    def get_metric(
        self,
        metric: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> MetricSeries:
        if metric not in self._metric_queries:
            raise KeyError(metric)
        win_start, win_end = self._window(start, end)
        resp = self._client.get(
            "/api/v1/query",
            params={"from": _epoch(win_start), "to": _epoch(win_end),
                    "query": self._metric_queries[metric]},
        )
        resp.raise_for_status()
        series = resp.json().get("series") or []
        points: list[MetricPoint] = []
        if series:
            for ts_ms, value in series[0].get("pointlist", []):
                if value is None:
                    continue
                points.append(MetricPoint(
                    timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                    value=float(value),
                ))
        return MetricSeries(metric=metric, points=points)

    def get_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[TelemetryEvent]:
        win_start, win_end = self._window(start, end)
        resp = self._client.get(
            "/api/v1/events",
            params={"start": _epoch(win_start), "end": _epoch(win_end)},
        )
        resp.raise_for_status()
        out: list[TelemetryEvent] = []
        for ev in resp.json().get("events", []):
            out.append(TelemetryEvent(
                id=str(ev.get("id")),
                timestamp=datetime.fromtimestamp(ev["date_happened"], tz=timezone.utc),
                source=_classify_source(ev),
                title=ev.get("title", ""),
                description=ev.get("text", ""),
                severity=_map_severity(ev.get("alert_type")),
                metadata={"tags": ev.get("tags", [])},
            ))
        return sorted(out, key=lambda e: e.timestamp)

    def time_range(self) -> tuple[datetime, datetime]:
        now = datetime.now(timezone.utc)
        return now - timedelta(hours=1), now

    def _window(self, start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
        if start is not None and end is not None:
            return start, end
        default_start, default_end = self.time_range()
        return (start or default_start), (end or default_end)
