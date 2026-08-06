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


def make_quantified_investigation() -> Investigation:
    """An investigation whose evidence carries real numbers and attribution —
    the shape the live adapter actually produces."""
    from app.reasoning.models import CoverageGap

    inv = make_investigation()
    inv.narrative = (
        "The 09:02 deploy changed cache key generation, so reads that had been "
        "served from cache went to the database and latency rose across checkout."
    )
    inv.evidence = {
        "met:ec.indexer.ingested_communication_event_latency": Evidence(
            id="met:ec.indexer.ingested_communication_event_latency",
            kind="metric", ref="ec.indexer.ingested_communication_event_latency",
            detail="p99 rose", service="ec-indexer", stage="8 indexed",
            unit="ms", has_data=True, points=142,
            baseline=590.0, latest=1840.0, extreme=2310.0,
        ),
        "met:ec.quota_manager.sampling_stats_counter": Evidence(
            id="met:ec.quota_manager.sampling_stats_counter",
            kind="metric", ref="ec.quota_manager.sampling_stats_counter",
            detail="no data returned in the selected window",
            service="ec-surveillance-quota-manager", stage="5 surveilled_sampled",
            unit="messages", has_data=False, points=0,
        ),
    }
    inv.facts = [
        ReasoningObject(
            claim="Indexing p99 reached 1,840ms.",
            category=ReasoningCategory.FACT,
            confidence=Confidence.HIGH,
            evidence=["met:ec.indexer.ingested_communication_event_latency"],
        )
    ]
    inv.gaps = [
        CoverageGap(
            topic="consumer_lag", kind="no_monitor",
            reason="57 dashboard widgets but ZERO monitors",
            check="open kafka_lags on ec_message_processing_summary_dashboard",
        )
    ]
    return inv


# --- the chat reply: directed prose, then hard data ------------------------

def test_reply_leads_with_the_quantitative_headline_not_the_narrative():
    """Prose belongs in the Workspace panel. The chat reply opens with the
    one-line headline and goes straight to data."""
    text = render(get_persona("sre"), make_quantified_investigation())

    assert text.startswith("Checkout latency rose")
    assert "cache key generation" not in text  # that is the Workspace's job


def test_a_fact_carries_the_metric_name_and_its_numbers():
    text = render(get_persona("sre"), make_quantified_investigation())

    assert "ec.indexer.ingested_communication_event_latency" in text
    assert "1,840" in text      # latest, thousands-separated
    assert "590" in text        # baseline
    assert "2,310" in text      # peak
    assert "142 pts" in text
    assert "ms" in text


def test_a_fact_is_attributed_to_its_stage_and_service():
    text = render(get_persona("sre"), make_quantified_investigation())
    assert "stage 8 indexed" in text
    assert "ec-indexer" in text


def test_confidence_is_emitted_as_a_bracket_token_for_the_ui_to_colour():
    text = render(get_persona("sre"), make_quantified_investigation())
    assert "[high]" in text


def test_coverage_gaps_appear_in_every_persona_reply():
    """A gap is exactly the kind of thing a non-technical reader would otherwise
    take as health, so no lens is allowed to drop it."""
    inv = make_quantified_investigation()
    for key in REGISTRY:
        text = render(get_persona(key), inv)
        assert "consumer lag" in text.lower(), f"{key} dropped the coverage gap"
        assert "kafka_lags" in text, f"{key} dropped the dashboard pointer"


def test_metrics_queried_appendix_lists_what_was_actually_asked_for():
    text = render(get_persona("sre"), make_quantified_investigation())
    assert "Metrics queried" in text
    assert "ec.quota_manager.sampling_stats_counter" in text


def test_a_metric_that_returned_nothing_says_so_rather_than_being_hidden():
    text = render(get_persona("sre"), make_quantified_investigation())
    assert "no data" in text.lower()


def test_low_detail_personas_stay_terse_but_keep_the_numbers():
    """Leadership loses evidence ids and the metrics appendix, never the
    measurement — that was the whole complaint."""
    inv = make_quantified_investigation()
    lead = render(get_persona("leadership"), inv)
    sre = render(get_persona("sre"), inv)

    assert "Metrics queried" not in lead
    assert "met:" not in lead
    assert len(lead) < len(sre)


def test_render_is_still_deterministic_and_llm_free():
    inv = make_quantified_investigation()
    assert render(get_persona("sre"), inv) == render(get_persona("sre"), inv)


def test_an_investigation_with_no_numbers_still_renders():
    """Replay data and older snapshots carry bare Evidence with no metrics."""
    text = render(get_persona("sre"), make_investigation())
    assert "Checkout latency rose" in text
    assert "API p95 latency rose" in text


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
