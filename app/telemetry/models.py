"""Normalized telemetry domain model.

Every data source (replay, live Datadog, future backends) maps its raw signals
into these types so the reasoning layer is decoupled from any vendor format.
Events from all sources share one timestamped shape so they merge into a single
ordered timeline.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from pydantic import BaseModel, Field

#: Hard ceiling on a custom investigation window. Bounds token cost: a scope can
#: never pull more than a week of telemetry into the reasoning path.
MAX_SCOPE_DAYS = 7


class EventSource(str, Enum):
    DEPLOY = "deploy"
    METRIC = "metric"
    LOG = "log"
    TRACE = "trace"
    SUPPORT = "support"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Severity ordering (INFO < WARNING < CRITICAL) for sorting/peak picks."""
        return {"info": 0, "warning": 1, "critical": 2}[self.value]


class TelemetryEvent(BaseModel):
    """A normalized, timestamped event for the unified incident timeline."""

    id: str
    timestamp: datetime
    source: EventSource
    title: str
    description: str = ""
    severity: Severity = Severity.INFO
    service: str | None = None
    metadata: dict = Field(default_factory=dict)


class Scope(BaseModel):
    """The investigation lens: which environments/tenants to inspect and over what
    window. Persisted per conversation, overridable per message, and translated by
    each DataSource into its own query filter. At least one of environments/tenants
    must be selected, and the window is capped at MAX_SCOPE_DAYS.
    """

    environments: list[str] = Field(default_factory=list)
    tenants: list[str] = Field(default_factory=list)
    start: datetime | None = None
    end: datetime | None = None

    def has_selection(self) -> bool:
        return bool(self.environments or self.tenants)

    def validation_error(self, max_days: int = MAX_SCOPE_DAYS) -> str | None:
        """Return a human-readable reason the scope is unusable, or None if valid.

        The 'end ≤ now' rule is intentionally NOT enforced here (it needs the wall
        clock and would make this impure); the API clamps the window to now.
        """
        if not self.has_selection():
            return "Select at least one environment or tenant."
        if self.start is None or self.end is None:
            return "A duration is required."
        if self.end < self.start:
            return "The end of the range must be after its start."
        if self.end - self.start > timedelta(days=max_days):
            return f"Duration cannot exceed {max_days} days."
        return None


class MetricPoint(BaseModel):
    timestamp: datetime
    value: float


class MetricSeries(BaseModel):
    """A single metric's time series, with small aggregation helpers used by the
    reasoning layer."""

    metric: str
    service: str | None = None
    unit: str = ""
    points: list[MetricPoint] = Field(default_factory=list)

    def max_value(self) -> float:
        return max(p.value for p in self.points)

    def min_value(self) -> float:
        return min(p.value for p in self.points)

    def latest(self) -> MetricPoint | None:
        return self.points[-1] if self.points else None
