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

from app.reasoning.models import Confidence, Investigation


def hypothesis_key(statement: str) -> str:
    """Stable identity for a hypothesis across snapshots, derived from its text,
    so confidence movement can be tracked even though each reasoning pass emits
    fresh objects with no stable id. Case- and whitespace-insensitive."""
    return re.sub(r"\s+", " ", statement or "").strip().lower()


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
    return [evt for evt in inv.timeline if evt.source.value == "support"]


def _recommended_next_steps(inv: Investigation):
    return list(inv.recommendations)


def _outstanding_questions(inv: Investigation):
    # Declared unknowns + everything every hypothesis says it is missing.
    questions = [u.claim for u in inv.unknowns]
    for h in inv.hypotheses:
        questions.extend(h.missing_information)
    return questions


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
