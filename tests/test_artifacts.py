"""Spec for operational artifacts (kickoff §5.10).

An artifact is a TRANSFORM over the same Workspace/Investigation state — it
invents nothing, it reshapes existing findings for a specific audience. The set
is registry-driven so new artifact types are added without touching reasoning.
Iteration 0 ships one: the Incident Summary (for incident-response teams).
"""
from datetime import datetime, timezone

import pytest

from app.artifacts import REGISTRY, render_artifact
from app.reasoning.models import (
    Confidence,
    Evidence,
    Hypothesis,
    Investigation,
    ReasoningCategory,
    ReasoningObject,
)
from app.telemetry.models import EventSource, Severity, TelemetryEvent


def make_investigation() -> Investigation:
    return Investigation(
        question="Why is checkout slow?",
        summary="Checkout latency rose ~10 min after the 09:02 deploy; customers see slowness, not errors.",
        facts=[
            ReasoningObject(
                claim="API p95 latency rose from 120ms to 480ms.",
                category=ReasoningCategory.FACT,
                confidence=Confidence.HIGH,
                evidence=["met:api.latency.p95"],
            )
        ],
        hypotheses=[
            Hypothesis(
                statement="A minor config drift contributed.",
                confidence=Confidence.LOW,
                supporting_evidence=[],
                contradicting_evidence=[],
                missing_information=[],
            ),
            Hypothesis(
                statement="The 09:02 deployment introduced a latency regression.",
                confidence=Confidence.HIGH,
                supporting_evidence=["evt:e1", "met:api.latency.p95"],
                contradicting_evidence=[],
                missing_information=["DB connection-pool metrics"],
            ),
        ],
        recommendations=[
            ReasoningObject(
                claim="Roll back the 09:02 deployment.",
                category=ReasoningCategory.RECOMMENDATION,
                confidence=Confidence.MEDIUM,
            )
        ],
        unknowns=[
            ReasoningObject(
                claim="Cross-service blast radius is unknown.",
                category=ReasoningCategory.UNKNOWN,
            )
        ],
        timeline=[
            TelemetryEvent(
                id="e1",
                timestamp=datetime(2026, 6, 26, 9, 2, tzinfo=timezone.utc),
                source=EventSource.DEPLOY,
                title="Deploy v1.2.3",
                severity=Severity.INFO,
                service="checkout",
            ),
            TelemetryEvent(
                id="e2",
                timestamp=datetime(2026, 6, 26, 9, 12, tzinfo=timezone.utc),
                source=EventSource.METRIC,
                title="API p95 exceeded SLO",
                severity=Severity.CRITICAL,
                service="checkout",
            ),
        ],
        evidence={
            "met:api.latency.p95": Evidence(
                id="met:api.latency.p95", kind="metric",
                ref="api.latency.p95", detail="p95 rose 120ms -> 480ms",
            ),
        },
    )


def test_registry_contains_incident_summary():
    assert "incident_summary" in REGISTRY


def test_unknown_artifact_raises():
    with pytest.raises(KeyError):
        render_artifact("does_not_exist", make_investigation())


def test_incident_summary_has_audience_and_core_sections():
    doc = render_artifact("incident_summary", make_investigation(), incident_id="replay-demo")
    assert doc.key == "incident_summary"
    assert doc.audience  # who it's for
    headings = {s.heading for s in doc.sections}
    assert {"Summary", "Severity", "Timeline", "Likely Cause", "Recommended Next Steps"} <= headings


def test_incident_summary_picks_highest_confidence_hypothesis():
    doc = render_artifact("incident_summary", make_investigation())
    cause = next(s.body for s in doc.sections if s.heading == "Likely Cause")
    assert "latency regression" in cause       # the HIGH-confidence one
    assert "config drift" not in cause          # not the LOW-confidence one
    assert "high" in cause.lower()              # confidence is stated


def test_incident_summary_severity_derived_from_timeline():
    doc = render_artifact("incident_summary", make_investigation())
    sev = next(s.body for s in doc.sections if s.heading == "Severity")
    assert "critical" in sev.lower()            # a CRITICAL event is present


def test_incident_summary_is_grounded_transform():
    doc = render_artifact("incident_summary", make_investigation())
    body = doc.to_markdown()
    assert "Checkout latency rose" in body      # the investigation summary
    assert "Roll back the 09:02 deployment." in body  # the recommendation, verbatim


def test_to_markdown_renders_title_and_headings():
    md = render_artifact("incident_summary", make_investigation()).to_markdown()
    assert md.startswith("# ")
    assert "## Summary" in md
    assert "## Recommended Next Steps" in md
