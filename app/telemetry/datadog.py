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
from app.telemetry.namespaces import matches
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

# What Datadog reports as the tag value when a series doesn't carry the tag being
# grouped on (seen live as `env:N/A` on a metric with no env tag).
_MISSING_TAG_VALUE = "N/A"


def _or_group(key: str, values: list[str]) -> str:
    terms = [f"{key}:{v}" for v in values]
    body = " OR ".join(terms)
    return f"({body})" if len(terms) > 1 else body

# Broadly-present Datadog Agent infra signals — a useful default that actually
# returns data on most orgs. Override per-org with DATADOG_METRIC_QUERIES (JSON)
# to point at your golden signals (APM latency/errors/throughput, etc.).
_DEFAULT_METRIC_QUERIES: dict[str, str] = {
    "system.cpu.user": "avg:system.cpu.user{*}",
    "system.load.1": "avg:system.load.1{*}",
    "system.mem.used": "avg:system.mem.used{*}",
    "system.disk.in_use": "avg:system.disk.in_use{*}",
}

# How far back metric-name discovery looks for *actively reporting* metrics. A day
# is long enough to survive a quiet overnight window without dragging in metrics
# that stopped being emitted long ago.
DISCOVERY_LOOKBACK_HOURS = 24

# Aggregation used for a live-discovered metric name. Terraform-extracted queries
# take precedence precisely because they carry the real aggregation instead.
DISCOVERED_AGGREGATION = "avg"


def discovered_queries(names: list[str]) -> dict[str, str]:
    """Turn discovered metric names into an adapter-ready {name: query} map."""
    return {n: f"{DISCOVERED_AGGREGATION}:{n}{{*}}" for n in names}


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _auth_headers(api_key: str, app_key: str, access_token: str) -> dict[str, str]:
    """A Personal Access Token authenticates on its own (Bearer); fall back to the
    legacy API-key + Application-key header pair when no token is given."""
    if access_token:
        return {"Authorization": f"Bearer {access_token}"}
    return {"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key}


def _make_client(
    site: str,
    headers: dict[str, str],
    verify: bool | str,
    transport: httpx.BaseTransport | None,
    timeout: float,
) -> httpx.Client:
    """`verify` accepts a CA-bundle path (corporate TLS-inspection proxies) or a
    bool. Ignored when a custom transport is injected (i.e. in tests)."""
    return httpx.Client(
        base_url=f"https://api.{site}",
        headers=headers,
        verify=verify,
        transport=transport,
        timeout=timeout,
    )


def _names_from_metrics_list(body: object) -> list[str]:
    """Pull metric names out of a metrics-list response, tolerantly.

    NOTE: the exact shape this endpoint returns for a given org/credential is not
    yet verified against a live org (see scripts/datadog_probe.py). Both the v1
    `{"metrics": [name, ...]}` and a v2-style `{"data": [{"id": name}, ...]}` body
    are accepted; anything else yields no names rather than an error.
    """
    if not isinstance(body, dict):
        return []
    raw = body.get("metrics")
    if isinstance(raw, list):
        return [n for n in raw if isinstance(n, str)]
    data = body.get("data")
    if isinstance(data, list):
        return [
            item["id"] for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
    return []


def discover_metric_names(
    patterns: tuple[str, ...],
    api_key: str = "",
    app_key: str = "",
    access_token: str = "",
    site: str = "datadoghq.com",
    verify: bool | str = True,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 15.0,
    lookback_hours: int = DISCOVERY_LOOKBACK_HOURS,
) -> list[str]:
    """Ask Datadog which metric names it has actively seen, narrowed to `patterns`.

    This is how a namespace like `ec.*` becomes a concrete registry of hundreds of
    metrics without anyone listing them by hand. It is **best-effort**: any
    failure (HTTP error, auth scope, unexpected body) yields an empty list so the
    app degrades to the Terraform-extracted metrics instead of failing to start.
    Returns nothing at all when no namespaces are configured — an unbounded
    "every metric in the org" registry is never what we want.
    """
    if not patterns:
        return []
    client = _make_client(
        site, _auth_headers(api_key, app_key, access_token), verify, transport, timeout)
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        resp = client.get("/api/v1/metrics", params={"from": _epoch(since)})
        resp.raise_for_status()
        names = _names_from_metrics_list(resp.json())
    except Exception:  # noqa: BLE001 - discovery is optional; never break startup
        return []
    finally:
        client.close()
    return sorted(n for n in names if matches(n, patterns))


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
        env_tag: str = "env",
        verify: bool | str = True,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        # `metric_queries` is the resolved in-scope registry (see
        # copilot.merged_metric_queries). None means "nothing was resolved" and only
        # then do the broadly-present infra defaults apply; an explicitly EMPTY dict
        # means the configured namespaces matched nothing, and falling back to
        # system.* there would contradict "only these metrics are in scope".
        self._metric_queries = (
            dict(_DEFAULT_METRIC_QUERIES) if metric_queries is None else dict(metric_queries))
        self._tenant_tag = tenant_tag
        # Neither dimension is a fixed Datadog concept. `env` is the *conventional*
        # environment tag but not a guaranteed one — verified live 2026-08-05 on a
        # real org that carries no `env` at all (grouping yields only `env:N/A`) and
        # expresses environment as `kube_namespace`. Hardcoding "env" would make
        # every environment filter silently match nothing.
        self._env_tag = env_tag
        self._client = _make_client(
            site, _auth_headers(api_key, app_key, access_token), verify, transport, timeout)

    def list_metrics(self) -> list[str]:
        return list(self._metric_queries.keys())

    def list_scopes(self, environments: list[str] | None = None) -> dict[str, list[str]]:
        # Only reached when no static COPILOT_PLATFORM_ENVIRONMENTS/_TENANTS list is
        # configured (see Copilot.list_scopes) — those short-circuit this entirely.
        if not self._metric_queries:
            return {"environments": [], "tenants": []}
        return {
            "environments": self._distinct_tag_values(self._env_tag),
            "tenants": self._distinct_tag_values(self._tenant_tag, env_filter=environments),
        }

    def _distinct_tag_values(self, key: str, env_filter: list[str] | None = None) -> list[str]:
        """Enumerate distinct values of a tag `key` by grouping an **in-scope**
        metric by that tag over the recent window; optionally constrained to
        selected envs. Using a metric from the registry (rather than a separately
        configured infra metric like system.cpu.user) means tag discovery reflects
        the platform actually being investigated.
        Tolerant of Datadog response shape — see OPEN-QUESTIONS (validate live)."""
        scope_body = _or_group(self._env_tag, env_filter) if env_filter else "*"
        query = f"{next(iter(self._metric_queries))}{{{scope_body}}} by {{{key}}}"
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
        # Datadog returns a literal "N/A" bucket for series that don't carry the tag
        # at all — not a selectable value, so it never belongs in the @ scope menu.
        return sorted(v for v in values if v and v != _MISSING_TAG_VALUE)

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
                title=ev.get("title") or "",
                description=ev.get("text") or "",
                severity=_map_severity(ev.get("alert_type")),
                metadata={"tags": ev.get("tags") or []},
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
            groups.append(_or_group(self._env_tag, scope.environments))
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
            tags.append(f"{self._env_tag}:{scope.environments[0]}")
        if len(scope.tenants) == 1:
            tags.append(f"{self._tenant_tag}:{scope.tenants[0]}")
        return ",".join(tags) or None
