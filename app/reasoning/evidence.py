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


def build_evidence_catalog(
    source: DataSource, scope: Scope | None = None
) -> tuple[dict[str, Evidence], str]:
    catalog: dict[str, Evidence] = {}
    lines: list[str] = []

    for e in source.get_events(scope=scope):
        eid = f"evt:{e.id}"
        detail = f"[{e.timestamp:%H:%M}] {e.title} (source={e.source.value}, severity={e.severity.value})"
        catalog[eid] = Evidence(id=eid, kind="event", ref=e.id, detail=detail)
        lines.append(f"{eid}: {detail}")

    for name in source.list_metrics():
        series = source.get_metric(name, scope=scope)
        if not series.points:
            continue
        mid = f"met:{name}"
        baseline = series.points[0].value
        latest = series.points[-1].value
        # "extreme" = the point that deviates most from baseline (the spike/dip).
        extreme = max(series.points, key=lambda p: abs(p.value - baseline)).value
        detail = (
            f"{name} ({series.unit}) on {series.service or 'unknown'}: "
            f"baseline={baseline}, peak/min={extreme}, latest={latest}"
        )
        catalog[mid] = Evidence(id=mid, kind="metric", ref=name, detail=detail)
        lines.append(f"{mid}: {detail}")

    return catalog, "\n".join(lines)
