"""Registry/config-driven Workspace sections.

The Workspace auto-organises an Investigation into meaningful sections. Sections
are DATA (a registry), not hard-coded UI branches — adding a new section is a
one-line append here plus a populate function, so the section set can grow
without touching the store, personas, or artifacts (kickoff §5.9).

Each section is a pure transform from an `Investigation` into displayable
content; the presentation layer interprets the content by section key.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from app.reasoning.models import (
    Confidence,
    Evidence,
    Hypothesis,
    Investigation,
    ReasoningObject,
)
from app.telemetry.models import EventSource, TelemetryEvent


def hypothesis_key(statement: str) -> str:
    """Stable identity for a hypothesis across snapshots, derived from its text,
    so confidence movement can be tracked even though each reasoning pass emits
    fresh objects with no stable id. Case- and whitespace-insensitive."""
    return re.sub(r"\s+", " ", statement or "").strip().lower()


def outstanding_questions(inv: Investigation) -> list[str]:
    """The investigation's open threads: explicitly declared unknowns plus the
    missing information each hypothesis still needs. Shared by the Workspace
    section and the artifact layer so the two never drift."""
    questions = [u.claim for u in inv.unknowns]
    for h in inv.hypotheses:
        questions.extend(h.missing_information)
    return questions


@dataclass(frozen=True)
class SectionView:
    key: str
    title: str
    order: int
    content: object


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    order: int
    populate: Callable[[Investigation], object]


# --- populate functions (pure: Investigation -> content) -------------------

def _executive_summary(inv: Investigation) -> str:
    return inv.summary


def _current_health(inv: Investigation):
    # Health is told through the observed facts.
    return list(inv.facts)


def _timeline(inv: Investigation):
    return list(inv.timeline)


def _evidence(inv: Investigation):
    return dict(inv.evidence)


def _correlated_signals(inv: Investigation):
    # Metric-derived evidence is the raw material for correlation.
    return [e for e in inv.evidence.values() if e.kind == "metric"]


def _root_cause(inv: Investigation):
    return list(inv.hypotheses)


def _affected_services(inv: Investigation):
    services: list[str] = []
    for evt in inv.timeline:
        if evt.service and evt.service not in services:
            services.append(evt.service)
    return services


def _customer_impact(inv: Investigation):
    # Support-sourced timeline entries are the clearest customer-impact signal.
    return [evt for evt in inv.timeline if evt.source == EventSource.SUPPORT]


def _recommended_next_steps(inv: Investigation):
    return list(inv.recommendations)


def _outstanding_questions(inv: Investigation):
    return outstanding_questions(inv)


def _confidence_assessment(inv: Investigation):
    # A compact map of each active hypothesis to its current confidence.
    return {h.statement: h.confidence for h in inv.hypotheses}


# --- the registry (config-driven, extensible) ------------------------------

REGISTRY: list[Section] = [
    Section("executive_summary", "Executive Summary", 10, _executive_summary),
    Section("current_health", "Current System Health", 20, _current_health),
    Section("timeline", "Timeline of Events", 30, _timeline),
    Section("evidence", "Observed Evidence", 40, _evidence),
    Section("correlated_signals", "Correlated Signals", 50, _correlated_signals),
    Section("root_cause", "Root Cause Hypotheses", 60, _root_cause),
    Section("affected_services", "Affected Services", 70, _affected_services),
    Section("customer_impact", "Customer Impact", 80, _customer_impact),
    Section("recommended_next_steps", "Recommended Next Steps", 90, _recommended_next_steps),
    Section("outstanding_questions", "Outstanding Questions", 100, _outstanding_questions),
    Section("confidence", "Confidence Assessment", 110, _confidence_assessment),
]


def render_sections(inv: Investigation) -> list[SectionView]:
    """Render the full ordered set of sections from an Investigation."""
    return [
        SectionView(s.key, s.title, s.order, s.populate(inv))
        for s in sorted(REGISTRY, key=lambda s: s.order)
    ]


# --- presentation serialization (for the live Workspace panel) -------------

def _serialize_content(content: object) -> dict:
    """Map a section's heterogeneous content to a JSON-friendly payload tagged
    with a display `kind`, dispatched on the content's type so new sections
    serialize automatically as long as they reuse the existing content types."""
    if isinstance(content, str):
        return {"kind": "text", "text": content}

    if isinstance(content, dict):
        values = list(content.values())
        if values and isinstance(values[0], Evidence):
            return {"kind": "evidence", "items": [e.model_dump() for e in values]}
        # confidence map {statement: Confidence}
        return {"kind": "kv", "items": [
            {"label": k, "value": getattr(v, "value", str(v))} for k, v in content.items()
        ]}

    if isinstance(content, list):
        if not content:
            return {"kind": "empty", "items": []}
        first = content[0]
        if isinstance(first, TelemetryEvent):
            return {"kind": "timeline", "items": [{
                "time": e.timestamp.strftime("%H:%M"),
                "title": e.title,
                "severity": e.severity.value,
                "source": e.source.value,
                "service": e.service,
            } for e in content]}
        if isinstance(first, Hypothesis):
            return {"kind": "hypotheses", "items": [{
                "statement": h.statement,
                "confidence": h.confidence.value,
                "supporting": h.supporting_evidence,
                "contradicting": h.contradicting_evidence,
                "missing": h.missing_information,
            } for h in content]}
        if isinstance(first, ReasoningObject):
            return {"kind": "claims", "items": [{
                "claim": r.claim, "confidence": r.confidence.value, "evidence": r.evidence,
            } for r in content]}
        if isinstance(first, Evidence):
            return {"kind": "evidence", "items": [e.model_dump() for e in content]}
        if isinstance(first, str):
            return {"kind": "list", "items": list(content)}

    return {"kind": "text", "text": str(content)}


def serialize_sections(inv: Investigation) -> list[dict]:
    """The full ordered section set as JSON-friendly dicts for the UI panel."""
    out = []
    for view in render_sections(inv):
        out.append({
            "key": view.key,
            "title": view.title,
            "order": view.order,
            **_serialize_content(view.content),
        })
    return out
