"""Spec for the persona layer (kickoff §5.1).

Personas are registry-driven config — adding one never touches core reasoning.
A persona changes only the *rendering lens* (which concerns lead, vocabulary,
detail depth); it must NEVER alter the underlying facts or evidence. Rendering
is deterministic and grounded in the Investigation (no LLM call), so it is cheap
and fully testable offline.
"""
from datetime import datetime, timezone

from app.personas import REGISTRY, Persona, get_persona, render
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
                statement="The 09:02 deployment introduced a latency regression.",
                confidence=Confidence.MEDIUM,
                supporting_evidence=["evt:e1", "met:api.latency.p95"],
                contradicting_evidence=[],
                missing_information=["DB connection-pool metrics"],
            )
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
                service="checkout",
            ),
            TelemetryEvent(
                id="e2",
                timestamp=datetime(2026, 6, 26, 9, 15, tzinfo=timezone.utc),
                source=EventSource.SUPPORT,
                title="Support tickets spiked",
                severity=Severity.WARNING,
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


def test_registry_has_the_five_charter_personas():
    assert set(REGISTRY) == {"support", "sre", "swe", "pm", "leadership"}


def test_persona_is_config_with_a_lens_not_facts():
    sre = REGISTRY["sre"]
    assert isinstance(sre, Persona)
    assert sre.lead_sections          # which concerns to surface first
    assert sre.detail in {"low", "medium", "high"}
    assert sre.label


def test_get_persona_defaults_to_sre_on_unknown():
    assert get_persona("nope").key == "sre"
    assert get_persona("pm").key == "pm"


def test_render_is_grounded_in_the_investigation():
    text = render(get_persona("sre"), make_investigation())
    # The narrative summary always leads.
    assert "Checkout latency rose" in text
    # SRE gets full technical depth: the root-cause hypothesis appears.
    assert "latency regression" in text


def test_render_changes_with_persona_same_facts():
    inv = make_investigation()
    sre_text = render(get_persona("sre"), inv)
    pm_text = render(get_persona("pm"), inv)
    # Same facts, different lens → different rendered text.
    assert sre_text != pm_text
    # Both still lead with the same factual narrative — facts are not altered.
    assert "Checkout latency rose" in sre_text
    assert "Checkout latency rose" in pm_text


def test_leadership_is_more_concise_than_sre():
    inv = make_investigation()
    assert len(render(get_persona("leadership"), inv)) < len(render(get_persona("sre"), inv))


def test_pm_surfaces_customer_impact_and_recommendation():
    text = render(get_persona("pm"), make_investigation())
    assert "Roll back" in text            # recommended next step
    assert "Support tickets" in text       # customer-impact signal
