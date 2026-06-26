"""Timeline reconstruction: merge all normalized events into one ordered story."""
from __future__ import annotations

from app.telemetry.models import TelemetryEvent


def build_timeline(events: list[TelemetryEvent]) -> list[TelemetryEvent]:
    """Return events sorted chronologically. Events already share one normalized
    shape, so any mix of sources merges into a single ordered timeline."""
    return sorted(events, key=lambda e: e.timestamp)
