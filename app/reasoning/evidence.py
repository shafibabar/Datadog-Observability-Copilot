"""Evidence catalog — the grounding layer.

Builds a catalog of citable evidence from a DataSource (every event and every
metric, with computed deltas) plus a compact context string listing each id.
The reasoning prompt hands the model this catalog and requires it to cite ids,
so every claim is traceable down to real telemetry and the model can't invent
support that isn't in the data.
"""
from __future__ import annotations

from app.reasoning.models import Evidence
from app.telemetry.base import DataSource
from app.telemetry.models import Scope

# Cap how many events enter the prompt. A live source can return thousands; an
# unbounded catalog makes the prompt huge, slow, and expensive. We keep the most
# recent events (the incident is "now"-anchored) and note any truncation.
MAX_CATALOG_EVENTS = 60


def build_evidence_catalog(
    source: DataSource,
    scope: Scope | None = None,
    metrics: list[str] | None = None,
) -> tuple[dict[str, Evidence], str]:
    """Build the citable-evidence catalog.

    `metrics` restricts which metric series are fetched (the resolver's bounded
    selection for large extracted registries); None keeps the original
    query-everything behavior for small registries (replay, infra defaults).
    """
    catalog: dict[str, Evidence] = {}
    lines: list[str] = []

    events = source.get_events(scope=scope)
    if len(events) > MAX_CATALOG_EVENTS:
        events = sorted(events, key=lambda e: e.timestamp)[-MAX_CATALOG_EVENTS:]
        lines.append(f"(showing the {MAX_CATALOG_EVENTS} most recent events of many)")
    for e in events:
        eid = f"evt:{e.id}"
        detail = f"[{e.timestamp:%H:%M}] {e.title} (source={e.source.value}, severity={e.severity.value})"
        catalog[eid] = Evidence(
            id=eid, kind="event", ref=e.id, detail=detail,
            service=e.service, time=f"{e.timestamp:%H:%M}", severity=e.severity.value,
        )
        lines.append(f"{eid}: {detail}")

    registered = source.list_metrics()
    names = [m for m in metrics if m in registered] if metrics is not None else registered
    for name in names:
        series = source.get_metric(name, scope=scope)
        mid = f"met:{name}"

        # A queried-but-empty metric is kept, clearly marked. Dropping it made a
        # metric we looked at indistinguishable from one we never asked about,
        # and left the reader unable to tell "healthy" from "no signal" — the
        # live org's metrics are sparse enough for that to matter.
        if not series.points:
            detail = f"{name}: no data returned in the selected window"
            catalog[mid] = Evidence(
                id=mid, kind="metric", ref=name, detail=detail,
                service=series.service, unit=series.unit, has_data=False, points=0,
            )
            lines.append(f"{mid}: {detail}")
            continue

        baseline = series.points[0].value
        latest = series.points[-1].value
        # "extreme" = the point that deviates most from baseline (the spike/dip).
        extreme = max(series.points, key=lambda p: abs(p.value - baseline)).value
        detail = (
            f"{name} ({series.unit}) on {series.service or 'unknown'}: "
            f"baseline={baseline}, peak/min={extreme}, latest={latest}, "
            f"points={len(series.points)}"
        )
        catalog[mid] = Evidence(
            id=mid, kind="metric", ref=name, detail=detail,
            service=series.service, unit=series.unit, has_data=True,
            points=len(series.points),
            baseline=baseline, latest=latest, extreme=extreme,
        )
        lines.append(f"{mid}: {detail}")

    return catalog, "\n".join(lines)
