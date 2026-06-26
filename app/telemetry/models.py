"""Normalized telemetry domain model.

Every data source (replay, live Datadog, future backends) maps its raw signals
into these types so the reasoning layer is decoupled from any vendor format.
Events from all sources share one timestamped shape so they merge into a single
ordered timeline.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


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
