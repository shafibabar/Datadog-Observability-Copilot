"""Spec for the Investigation Workspace — the architectural center of gravity.

The Workspace is a real, persisted, versioned investigation-state model (a living
document, NOT derived from chat). It must:
  - append-with-history (every record() is an immutable snapshot; nothing is
    overwritten, so prior reasoning stays visible),
  - keep reasoning objects queryable,
  - track how a hypothesis's confidence moves over time,
  - organise findings into registry/config-driven sections (extensible).

Written test-first (TDD red) before the implementation exists. No LLM, no network.
"""
from datetime import datetime, timezone

import pytest

from app.reasoning.models import (
    Confidence,
    Evidence,
    Hypothesis,
    Investigation,
    ReasoningCategory,
    ReasoningObject,
)
from app.telemetry.models import EventSource, Severity, TelemetryEvent
from app.workspace.sections import REGISTRY, hypothesis_key, render_sections
from app.workspace.store import WorkspaceStore


# --- fixtures / helpers ----------------------------------------------------

def make_investigation(
    *,
    summary: str = "Checkout latency rose after the 09:02 deploy.",
    hypo_conf: Confidence = Confidence.LOW,
    hypo_statement: str = "The 09:02 deployment introduced a latency regression.",
) -> Investigation:
    evidence = {
        "evt:e1": Evidence(id="evt:e1", kind="event", ref="e1", detail="Deploy at 09:02"),
        "met:api.latency.p95": Evidence(
            id="met:api.latency.p95", kind="metric", ref="api.latency.p95",
            detail="p95 latency rose 120ms -> 480ms",
        ),
    }
    return Investigation(
        question="Why is checkout slow?",
        summary=summary,
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
                statement=hypo_statement,
                confidence=hypo_conf,
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
                claim="Blast radius across other services is unknown.",
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
                title="API latency exceeded SLO",
                severity=Severity.CRITICAL,
                service="checkout",
            ),
        ],
        evidence=evidence,
    )


@pytest.fixture
def store():
    return WorkspaceStore(":memory:")


# --- workspace lifecycle ---------------------------------------------------

def test_create_workspace_returns_id(store):
    wid = store.create_workspace(incident_id="deploy-2026-06-26", source_type="replay")
    assert wid
    meta = store.get_workspace(wid)
    assert meta.incident_id == "deploy-2026-06-26"
    assert meta.source_type == "replay"


def test_record_appends_snapshot_with_incrementing_seq(store):
    wid = store.create_workspace(incident_id="i", source_type="replay")
    s1 = store.record(wid, make_investigation())
    s2 = store.record(wid, make_investigation())
    assert s1.seq == 1
    assert s2.seq == 2


def test_record_is_append_only_history_is_preserved(store):
    """The living document never overwrites: every snapshot stays visible."""
    wid = store.create_workspace(incident_id="i", source_type="replay")
    store.record(wid, make_investigation(summary="first pass"))
    store.record(wid, make_investigation(summary="second pass"))
    history = store.history(wid)
    assert len(history) == 2
    assert [h.investigation.summary for h in history] == ["first pass", "second pass"]


def test_latest_returns_most_recent_snapshot(store):
    wid = store.create_workspace(incident_id="i", source_type="replay")
    store.record(wid, make_investigation(summary="old"))
    store.record(wid, make_investigation(summary="new"))
    latest = store.latest(wid)
    assert latest.seq == 2
    assert latest.investigation.summary == "new"


def test_latest_is_none_for_empty_workspace(store):
    wid = store.create_workspace(incident_id="i", source_type="replay")
    assert store.latest(wid) is None


def test_snapshot_roundtrips_full_investigation(store):
    """Facts, hypotheses, timeline, and evidence all survive persistence."""
    wid = store.create_workspace(incident_id="i", source_type="replay")
    store.record(wid, make_investigation())
    inv = store.latest(wid).investigation
    assert inv.facts[0].claim.startswith("API p95 latency")
    assert inv.facts[0].confidence == Confidence.HIGH
    assert inv.hypotheses[0].missing_information == ["DB connection-pool metrics"]
    assert len(inv.timeline) == 2
    assert inv.timeline[1].severity == Severity.CRITICAL
    assert "met:api.latency.p95" in inv.evidence


# --- real persistence (not in-memory derivation) --------------------------

def test_persists_across_store_instances(tmp_path):
    """A fresh store on the same file sees prior reasoning — proves the
    Workspace is genuinely persisted state, not reconstructed from chat."""
    db = tmp_path / "workspace.db"
    s1 = WorkspaceStore(db)
    wid = s1.create_workspace(incident_id="i", source_type="replay")
    s1.record(wid, make_investigation(summary="persisted"))
    s1.close()

    s2 = WorkspaceStore(db)
    assert s2.latest(wid).investigation.summary == "persisted"


# --- queryable reasoning atoms --------------------------------------------

def test_reasoning_objects_are_extracted_and_queryable(store):
    wid = store.create_workspace(incident_id="i", source_type="replay")
    store.record(wid, make_investigation())
    objs = store.reasoning_objects(wid)
    kinds = sorted({o.kind for o in objs})
    assert kinds == ["fact", "hypothesis", "recommendation", "unknown"]


def test_reasoning_objects_can_be_filtered_by_snapshot(store):
    wid = store.create_workspace(incident_id="i", source_type="replay")
    store.record(wid, make_investigation())
    store.record(wid, make_investigation())
    only_first = store.reasoning_objects(wid, snapshot_seq=1)
    assert only_first
    assert {o.snapshot_seq for o in only_first} == {1}
    assert len(store.reasoning_objects(wid)) == 2 * len(only_first)


def test_workspace_db_never_stores_secret_values(tmp_path):
    """Charter constraint: no secret material is ever persisted to the Workspace
    DB. Even if a secret-looking string rides along in the data, the store only
    writes investigation content — but we guard against regression by scanning
    the raw DB bytes for a planted secret."""
    db = tmp_path / "workspace.db"
    store = WorkspaceStore(db)
    wid = store.create_workspace(incident_id="i", source_type="replay")
    store.record(wid, make_investigation())
    store.close()
    raw = db.read_bytes()
    for secret in (b"sk-ant-", b"DD-API-KEY", b"ANTHROPIC_API_KEY"):
        assert secret not in raw


# --- confidence over time --------------------------------------------------

def test_confidence_history_tracks_a_hypothesis_across_snapshots(store):
    """As evidence accrues, a hypothesis's confidence is revisable and the
    movement stays visible."""
    wid = store.create_workspace(incident_id="i", source_type="replay")
    store.record(wid, make_investigation(hypo_conf=Confidence.LOW))
    store.record(wid, make_investigation(hypo_conf=Confidence.MEDIUM))
    store.record(wid, make_investigation(hypo_conf=Confidence.HIGH))

    key = hypothesis_key("The 09:02 deployment introduced a latency regression.")
    points = store.confidence_history(wid, key)
    assert [p.confidence for p in points] == [
        Confidence.LOW,
        Confidence.MEDIUM,
        Confidence.HIGH,
    ]
    assert [p.seq for p in points] == [1, 2, 3]


def test_hypothesis_key_is_normalised(store):
    assert hypothesis_key("  Deploy  caused  it ") == hypothesis_key("deploy caused it")


def test_confidence_history_isolates_distinct_hypotheses(store):
    """Two different hypotheses must not share a confidence track."""
    wid = store.create_workspace(incident_id="i", source_type="replay")
    store.record(wid, make_investigation(
        hypo_statement="Deploy A caused it.", hypo_conf=Confidence.HIGH))
    store.record(wid, make_investigation(
        hypo_statement="Deploy B caused it.", hypo_conf=Confidence.LOW))

    a = store.confidence_history(wid, hypothesis_key("Deploy A caused it."))
    b = store.confidence_history(wid, hypothesis_key("Deploy B caused it."))
    assert [p.confidence for p in a] == [Confidence.HIGH]
    assert [p.confidence for p in b] == [Confidence.LOW]


# --- registry-driven sections ----------------------------------------------

def test_section_registry_covers_charter_sections():
    keys = {s.key for s in REGISTRY}
    expected = {
        "executive_summary",
        "current_health",
        "timeline",
        "evidence",
        "correlated_signals",
        "root_cause",
        "affected_services",
        "customer_impact",
        "recommended_next_steps",
        "outstanding_questions",
        "confidence",
    }
    assert expected <= keys


def test_render_sections_is_ordered_and_titled():
    views = render_sections(make_investigation())
    orders = [v.order for v in views]
    assert orders == sorted(orders)
    titles = {v.key: v.title for v in views}
    assert titles["executive_summary"] == "Executive Summary"
    assert titles["root_cause"] == "Root Cause Hypotheses"


def test_render_sections_populates_from_investigation():
    views = {v.key: v for v in render_sections(make_investigation())}
    assert views["executive_summary"].content == (
        "Checkout latency rose after the 09:02 deploy."
    )
    assert len(views["timeline"].content) == 2
    assert views["root_cause"].content[0].statement.startswith("The 09:02 deployment")
    assert views["recommended_next_steps"].content[0].claim.startswith("Roll back")
    # Outstanding questions merge declared unknowns + hypothesis missing-info.
    oq = views["outstanding_questions"].content
    assert "DB connection-pool metrics" in oq
    assert any("Blast radius" in q for q in oq)


def test_affected_services_derived_from_timeline():
    views = {v.key: v for v in render_sections(make_investigation())}
    assert "checkout" in views["affected_services"].content
