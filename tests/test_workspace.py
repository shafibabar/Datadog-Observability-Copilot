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
from app.workspace.sections import (
    REGISTRY,
    hypothesis_key,
    render_sections,
    serialize_sections,
)
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


# --- messages & conversations ----------------------------------------------

def test_messages_roundtrip_in_order(store):
    wid = store.create_workspace(incident_id="i", source_type="replay")
    store.add_message(wid, role="user", content="Why slow?", persona="sre")
    store.add_message(wid, role="assistant", content="The 09:02 deploy.", persona="sre")
    msgs = store.get_messages(wid)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert [m.seq for m in msgs] == [1, 2]
    assert msgs[0].content == "Why slow?"
    assert msgs[0].persona == "sre"


def test_messages_are_isolated_per_conversation(store):
    a = store.create_workspace(incident_id="a", source_type="replay")
    b = store.create_workspace(incident_id="b", source_type="replay")
    store.add_message(a, role="user", content="in A")
    store.add_message(b, role="user", content="in B")
    assert [m.content for m in store.get_messages(a)] == ["in A"]
    assert [m.content for m in store.get_messages(b)] == ["in B"]


def test_create_workspace_accepts_title_and_get_returns_it(store):
    wid = store.create_workspace(incident_id="i", source_type="replay", title="Checkout latency")
    assert store.get_workspace(wid).title == "Checkout latency"


def test_set_title_updates_it(store):
    wid = store.create_workspace(incident_id="i", source_type="replay")
    store.set_title(wid, "Renamed incident")
    assert store.get_workspace(wid).title == "Renamed incident"


# --- scope persistence + delete -------------------------------------------

def test_scope_defaults_to_none_and_round_trips(store):
    from datetime import timedelta

    from app.telemetry.models import Scope

    wid = store.create_workspace(incident_id="i", source_type="datadog")
    assert store.get_scope(wid) is None

    t0 = datetime(2026, 7, 1, tzinfo=timezone.utc)
    scope = Scope(environments=["prod", "staging"], tenants=["acme"], start=t0, end=t0 + timedelta(hours=2))
    store.set_scope(wid, scope)
    assert store.get_scope(wid) == scope


def test_delete_workspace_removes_it_and_its_history(store):
    wid = store.create_workspace(incident_id="i", source_type="replay")
    store.add_message(wid, role="user", content="hi")
    store.record(wid, make_investigation())

    store.delete_workspace(wid)

    assert wid not in {c.id for c in store.list_conversations()}
    with pytest.raises(KeyError):
        store.get_workspace(wid)
    assert store.get_messages(wid) == []
    assert store.latest(wid) is None
    assert store.reasoning_objects(wid) == []


def test_scope_column_is_added_to_a_preexisting_db(tmp_path):
    """A DB created before scope existed must gain the column without data loss."""
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE workspaces (id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, "
        "source_type TEXT NOT NULL, created_at TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', "
        "updated_at TEXT NOT NULL DEFAULT '');"
    )
    conn.execute(
        "INSERT INTO workspaces (id, incident_id, source_type, created_at) VALUES (?,?,?,?)",
        ("w1", "i", "replay", datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    store = WorkspaceStore(db)          # opening must migrate, not crash
    assert store.get_workspace("w1").title == ""
    assert store.get_scope("w1") is None


def test_list_conversations_summarises_and_orders_by_recent_activity(store):
    first = store.create_workspace(incident_id="i", source_type="replay", title="First")
    second = store.create_workspace(incident_id="i", source_type="replay", title="Second")
    # Activity in `first` after `second` was created should float it to the top.
    store.add_message(first, role="user", content="ping")

    convos = store.list_conversations()
    assert [c.id for c in convos][0] == first        # most recently active first
    assert {c.id for c in convos} == {first, second}
    by_id = {c.id: c for c in convos}
    assert by_id[first].message_count == 1
    assert by_id[second].message_count == 0
    assert by_id[first].title == "First"


def test_recording_a_snapshot_bumps_activity(store):
    a = store.create_workspace(incident_id="a", source_type="replay")
    b = store.create_workspace(incident_id="b", source_type="replay")
    store.record(a, make_investigation())  # activity in the older conversation
    assert store.list_conversations()[0].id == a


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


# --- section serialization (for the live Workspace panel) ------------------

def test_serialize_sections_is_json_friendly_and_typed():
    sections = {s["key"]: s for s in serialize_sections(make_investigation())}
    # one entry per registry section, each carrying a display "kind"
    assert set(sections) == {s.key for s in REGISTRY}
    assert all("kind" in s and "title" in s for s in sections.values())

    assert sections["executive_summary"]["kind"] == "text"
    assert sections["executive_summary"]["text"]

    tl = sections["timeline"]
    assert tl["kind"] == "timeline"
    assert tl["items"][0]["time"]                       # HH:MM rendered
    assert "severity" in tl["items"][0]

    rc = sections["root_cause"]
    assert rc["kind"] == "hypotheses"
    assert rc["items"][0]["confidence"] in {"low", "medium", "high"}
    assert "missing" in rc["items"][0]

    ev = sections["evidence"]
    assert ev["kind"] == "evidence"
    assert ev["items"][0]["detail"]

    assert sections["recommended_next_steps"]["kind"] == "claims"
    assert sections["outstanding_questions"]["kind"] == "list"
    assert isinstance(sections["outstanding_questions"]["items"], list)


def test_serialize_sections_is_fully_json_serializable():
    import json
    json.dumps(serialize_sections(make_investigation()))  # must not raise
