"""The DataSource interface.

This is the seam the whole product is built around: the reasoning layer talks
only to this interface, so a replayed incident and a live Datadog org are
interchangeable. New backends implement these four methods.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.telemetry.models import MetricSeries, Scope, TelemetryEvent


class DataSource(ABC):
    #: Short identifier for the adapter (e.g. "replay", "datadog").
    source_type: str = "base"

    @abstractmethod
    def list_metrics(self) -> list[str]:
        """Names of the metrics this source can provide."""

    @abstractmethod
    def get_metric(
        self,
        metric: str,
        start: datetime | None = None,
        end: datetime | None = None,
        scope: Scope | None = None,
    ) -> MetricSeries:
        """Return one metric's series, optionally clipped to [start, end].

        A `scope` narrows the query to selected environments/tenants and (when it
        carries a window) overrides start/end. Sources that cannot honour a scope
        (e.g. the scripted replay) ignore it. Raises KeyError if the metric is
        unknown.
        """

    @abstractmethod
    def get_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        scope: Scope | None = None,
    ) -> list[TelemetryEvent]:
        """Return normalized events in chronological order, optionally clipped and
        scoped to selected environments/tenants."""

    @abstractmethod
    def time_range(self) -> tuple[datetime, datetime]:
        """The (start, end) window of data this source covers."""

    def list_scopes(self, environments: list[str] | None = None) -> dict[str, list[str]]:
        """Enumerate the environments/tenants a user can scope an investigation to,
        for the scope dropdowns. When `environments` is given, tenants are narrowed
        to those hosted on the selected environments. Default: nothing to offer."""
        return {"environments": [], "tenants": []}
