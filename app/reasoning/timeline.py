"""Timeline reconstruction: merge all normalized events into one ordered story."""
from __future__ import annotations

from app.telemetry.models import Severity, TelemetryEvent

#: Most events one timeline may carry. A live org returns ~1000 monitor events an
#: hour (measured), and an undifferentiated 1000-row list is neither a story a
#: human can read nor a payload worth shipping to the browser on every reply.
MAX_TIMELINE_EVENTS = 60

#: Kept in preference to routine noise when the timeline has to be trimmed.
_SIGNIFICANT = (Severity.CRITICAL, Severity.WARNING)


def build_timeline(
    events: list[TelemetryEvent], limit: int = MAX_TIMELINE_EVENTS
) -> list[TelemetryEvent]:
    """Return events as one chronologically ordered story, bounded to `limit`.

    Events already share one normalized shape, so any mix of sources merges into a
    single ordered timeline. When there are more than `limit`, significant events
    (critical/warning, deploys) are kept ahead of routine info noise, and the most
    recent are kept within each group — an incident is "now"-anchored. The result
    is always chronological regardless of what was dropped.
    """
    ordered = sorted(events, key=lambda e: e.timestamp)
    if len(ordered) <= limit:
        return ordered
    significant = [e for e in ordered if e.severity in _SIGNIFICANT]
    routine = [e for e in ordered if e.severity not in _SIGNIFICANT]
    kept = significant[-limit:]
    if len(kept) < limit:
        kept += routine[-(limit - len(kept)):]
    return sorted(kept, key=lambda e: e.timestamp)
