"""ReplayAdapter — a scripted, deterministic incident for reliable demos.

Canonical story (deployment-induced latency):
    09:02  Deployment initiated
    09:06  New version became active
    09:08  Cache hit ratio declined
    09:10  Database latency increased
    09:12  API p95 latency exceeded SLO  (customers experience slowness, not errors)
    09:15  Customer support tickets increased
    09:20  Rollback initiated
    09:27  Metrics returned to baseline

The data is generated deterministically (piecewise-linear shapes + a fixed
sinusoidal wiggle) so every replay is identical — but the AI reasoning over it
is genuine, never hard-coded.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.telemetry.base import DataSource
from app.telemetry.models import (
    EventSource,
    MetricPoint,
    MetricSeries,
    Scope,
    Severity,
    TelemetryEvent,
)

_ANCHOR = datetime(2024, 1, 15, 9, 0, tzinfo=timezone.utc)
_DURATION_MIN = 35  # 09:00 .. 09:35 inclusive


def _piecewise(minute: float, keyframes: list[tuple[float, float]]) -> float:
    """Linear interpolation across (minute, value) keyframes, clamped at the ends."""
    if minute <= keyframes[0][0]:
        return keyframes[0][1]
    if minute >= keyframes[-1][0]:
        return keyframes[-1][1]
    for (m0, v0), (m1, v1) in zip(keyframes, keyframes[1:]):
        if m0 <= minute <= m1:
            frac = (minute - m0) / (m1 - m0)
            return v0 + (v1 - v0) * frac
    return keyframes[-1][1]


# metric -> (unit, service, shape). shape is a callable(minute) -> value.
_METRICS: dict[str, tuple[str, str, object]] = {
    "api.latency.p95": (
        "ms",
        "checkout-api",
        lambda m: _piecewise(m, [(0, 120), (10, 120), (14, 480), (20, 480), (27, 125), (35, 122)]),
    ),
    "db.query.latency.p95": (
        "ms",
        "orders-db",
        lambda m: _piecewise(m, [(0, 30), (10, 30), (14, 180), (20, 180), (26, 32), (35, 31)]),
    ),
    "cache.hit_ratio": (
        "ratio",
        "redis-cache",
        lambda m: _piecewise(m, [(0, 0.95), (8, 0.95), (12, 0.60), (20, 0.60), (26, 0.94), (35, 0.95)]),
    ),
    "api.error_rate": (
        "percent",
        "checkout-api",
        lambda m: 0.5 + 0.05 * math.sin(m),  # stable: slowness, not failures
    ),
    "api.requests.rps": (
        "rps",
        "checkout-api",
        lambda m: 200 + 8 * math.sin(m / 2),  # roughly steady traffic
    ),
}


def _build_events() -> list[TelemetryEvent]:
    def at(mins: int) -> datetime:
        return _ANCHOR + timedelta(minutes=mins)

    return [
        TelemetryEvent(id="e1", timestamp=at(2), source=EventSource.DEPLOY,
                       title="Deployment initiated", service="checkout-api",
                       description="CI/CD pipeline started rollout of v2.4.1."),
        TelemetryEvent(id="e2", timestamp=at(6), source=EventSource.DEPLOY,
                       title="New version v2.4.1 became active", service="checkout-api",
                       description="All pods running v2.4.1."),
        TelemetryEvent(id="e3", timestamp=at(8), source=EventSource.METRIC, severity=Severity.WARNING,
                       title="Cache hit ratio began declining", service="redis-cache",
                       description="redis-cache hit ratio dropped below 0.90."),
        TelemetryEvent(id="e4", timestamp=at(10), source=EventSource.METRIC, severity=Severity.WARNING,
                       title="Database query latency increasing", service="orders-db",
                       description="orders-db p95 query latency rising as cache misses grow."),
        TelemetryEvent(id="e5", timestamp=at(12), source=EventSource.METRIC, severity=Severity.CRITICAL,
                       title="API p95 latency exceeded SLO (300ms)", service="checkout-api",
                       description="checkout-api p95 crossed the 300ms SLO threshold."),
        TelemetryEvent(id="e6", timestamp=at(15), source=EventSource.SUPPORT, severity=Severity.WARNING,
                       title="Customer support tickets increased",
                       description="Spike in 'checkout is slow' tickets."),
        TelemetryEvent(id="e7", timestamp=at(20), source=EventSource.DEPLOY,
                       title="Rollback initiated to v2.4.0", service="checkout-api",
                       description="On-call triggered rollback to the previous version."),
        TelemetryEvent(id="e8", timestamp=at(27), source=EventSource.METRIC, severity=Severity.INFO,
                       title="API latency returned to baseline", service="checkout-api",
                       description="Metrics recovered to pre-deploy levels."),
    ]


class ReplayAdapter(DataSource):
    source_type = "replay"

    def __init__(self) -> None:
        self._events = _build_events()
        self._series: dict[str, MetricSeries] = {}
        for name, (unit, service, shape) in _METRICS.items():
            points = [
                MetricPoint(timestamp=_ANCHOR + timedelta(minutes=m), value=round(float(shape(m)), 4))
                for m in range(_DURATION_MIN + 1)
            ]
            self._series[name] = MetricSeries(metric=name, service=service, unit=unit, points=points)

    def list_metrics(self) -> list[str]:
        return list(self._series.keys())

    # A small static scope set so the dropdowns (and their tests) work fully
    # offline against the scripted incident. The filter is intentionally a no-op:
    # the replay has no real per-environment tenancy.
    _ENVIRONMENTS = ["production", "staging"]
    _TENANTS = ["acme-corp", "globex", "initech"]

    def list_scopes(self, environments: list[str] | None = None) -> dict[str, list[str]]:
        return {"environments": list(self._ENVIRONMENTS), "tenants": list(self._TENANTS)}

    def get_metric(
        self,
        metric: str,
        start: datetime | None = None,
        end: datetime | None = None,
        scope: Scope | None = None,
    ) -> MetricSeries:
        # `scope` is accepted for interface parity but ignored: the replay is a
        # fixed, scripted historical incident with no environments/tenants and a
        # window that must not be clipped by a live scope's dates.
        if metric not in self._series:
            raise KeyError(metric)
        s = self._series[metric]
        pts = [
            p for p in s.points
            if (start is None or p.timestamp >= start) and (end is None or p.timestamp <= end)
        ]
        return MetricSeries(metric=s.metric, service=s.service, unit=s.unit, points=pts)

    def get_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        scope: Scope | None = None,
    ) -> list[TelemetryEvent]:  # `scope` ignored — see get_metric.
        events = [
            e for e in self._events
            if (start is None or e.timestamp >= start) and (end is None or e.timestamp <= end)
        ]
        return sorted(events, key=lambda e: e.timestamp)

    def time_range(self) -> tuple[datetime, datetime]:
        return _ANCHOR, _ANCHOR + timedelta(minutes=_DURATION_MIN)
