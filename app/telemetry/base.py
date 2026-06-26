"""The DataSource interface.

This is the seam the whole product is built around: the reasoning layer talks
only to this interface, so a replayed incident and a live Datadog org are
interchangeable. New backends implement these four methods.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.telemetry.models import MetricSeries, TelemetryEvent


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
    ) -> MetricSeries:
        """Return one metric's series, optionally clipped to [start, end].

        Raises KeyError if the metric is unknown.
        """

    @abstractmethod
    def get_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[TelemetryEvent]:
        """Return normalized events in chronological order, optionally clipped."""

    @abstractmethod
    def time_range(self) -> tuple[datetime, datetime]:
        """The (start, end) window of data this source covers."""
