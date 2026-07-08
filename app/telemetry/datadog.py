"""LiveDatadogAdapter — read-only access to a real Datadog org via its REST API.

Maps Datadog metric queries and events into the normalized telemetry model so it
is interchangeable with the ReplayAdapter behind the DataSource interface. Only
read endpoints are used. Keys are passed in (from app.config, never hard-coded).

Metric name -> Datadog query mapping is configurable per environment; the
defaults are illustrative golden-signal-style queries (see OPEN-QUESTIONS.md).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import httpx

from app.telemetry.base import DataSource
from app.telemetry.models import (
    EventSource,
    MetricPoint,
    MetricSeries,
    Scope,
    Severity,
    TelemetryEvent,
)

# The first {...} block in a Datadog metric query is the scope filter; we rewrite
# it from the Scope (later `by {...}` grouping blocks are left untouched).
_SCOPE_BRACE = re.compile(r"\{[^}]*\}")


def _or_group(key: str, values: list[str]) -> str:
    terms = [f"{key}:{v}" for v in values]
    body = " OR ".join(terms)
    return f"({body})" if len(terms) > 1 else body

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
        tenant_tag: str = "tenant",
        discovery_metric: str = "system.cpu.user",
        verify: bool | str = True,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._metric_queries = metric_queries or dict(_DEFAULT_METRIC_QUERIES)
        self._tenant_tag = tenant_tag
        self._discovery_metric = discovery_metric
        # A Personal Access Token authenticates on its own (Bearer); fall back to
        # the legacy API-key + Application-key header pair when no token is given.
        if access_token:
            headers = {"Authorization": f"Bearer {access_token}"}
        else:
            headers = {"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key}
        # `verify` accepts a CA-bundle path (corporate TLS-inspection proxies) or a
        # bool. Ignored when a custom transport is injected (i.e. in tests).
        self._client = httpx.Client(
            base_url=f"https://api.{site}",
            headers=headers,
            verify=verify,
            transport=transport,
            timeout=timeout,
        )

    def list_metrics(self) -> list[str]:
        return list(self._metric_queries.keys())

    def list_scopes(self, environments: list[str] | None = None) -> dict[str, list[str]]:
        return {
            "environments": self._distinct_tag_values("env"),
            "tenants": self._distinct_tag_values(self._tenant_tag, env_filter=environments),
        }

    def _distinct_tag_values(self, key: str, env_filter: list[str] | None = None) -> list[str]:
        """Enumerate distinct values of a tag `key` by grouping the discovery metric
        by that tag over the recent window; optionally constrained to selected envs.
        Tolerant of Datadog response shape — see OPEN-QUESTIONS (validate live)."""
        scope_body = _or_group("env", env_filter) if env_filter else "*"
        query = f"{self._discovery_metric}{{{scope_body}}} by {{{key}}}"
        start, end = self.time_range()
        resp = self._client.get(
            "/api/v1/query",
            params={"from": _epoch(start), "to": _epoch(end), "query": query},
        )
        resp.raise_for_status()
        prefix = f"{key}:"
        values: set[str] = set()
        for series in resp.json().get("series") or []:
            for tag in series.get("tag_set") or []:
                if tag.startswith(prefix):
                    values.add(tag[len(prefix):])
        return sorted(values)

    def get_metric(
        self,
        metric: str,
        start: datetime | None = None,
        end: datetime | None = None,
        scope: Scope | None = None,
    ) -> MetricSeries:
        if metric not in self._metric_queries:
            raise KeyError(metric)
        win_start, win_end = self._window(start, end, scope)
        query = self._apply_scope(self._metric_queries[metric], scope)
        resp = self._client.get(
            "/api/v1/query",
            params={"from": _epoch(win_start), "to": _epoch(win_end), "query": query},
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
        scope: Scope | None = None,
    ) -> list[TelemetryEvent]:
        win_start, win_end = self._window(start, end, scope)
        params = {"start": _epoch(win_start), "end": _epoch(win_end)}
        tags = self._event_tags(scope)
        if tags:
            params["tags"] = tags
        resp = self._client.get("/api/v1/events", params=params)
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

    def _window(
        self, start: datetime | None, end: datetime | None, scope: Scope | None = None
    ) -> tuple[datetime, datetime]:
        # A scope carrying a window wins; then explicit start/end; else last hour.
        if scope is not None and scope.start is not None and scope.end is not None:
            return scope.start, scope.end
        if start is not None and end is not None:
            return start, end
        default_start, default_end = self.time_range()
        return (start or default_start), (end or default_end)

    def _apply_scope(self, query: str, scope: Scope | None) -> str:
        """Rewrite the query's first `{...}` scope block from the Scope. No scope
        (or an empty one) leaves the original `{*}` untouched."""
        groups: list[str] = []
        if scope is not None and scope.environments:
            groups.append(_or_group("env", scope.environments))
        if scope is not None and scope.tenants:
            groups.append(_or_group(self._tenant_tag, scope.tenants))
        if not groups:
            return query
        return _SCOPE_BRACE.sub("{" + " AND ".join(groups) + "}", query, count=1)

    def _event_tags(self, scope: Scope | None) -> str | None:
        """Datadog's events `tags` param ANDs its entries, so we only filter a
        dimension when exactly one value is selected; multi-select dimensions are
        left to the time window (a documented limitation, see OPEN-QUESTIONS)."""
        if scope is None:
            return None
        tags: list[str] = []
        if len(scope.environments) == 1:
            tags.append(f"env:{scope.environments[0]}")
        if len(scope.tenants) == 1:
            tags.append(f"{self._tenant_tag}:{scope.tenants[0]}")
        return ",".join(tags) or None
