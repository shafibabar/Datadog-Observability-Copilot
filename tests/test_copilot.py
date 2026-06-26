"""Spec for the CopilotSession orchestrator.

Ties a DataSource + ReasoningEngine + Workspace into the chat loop:
  - asking a question runs a genuine investigation and APPENDS a snapshot
    (the living Workspace grows; prior reasoning stays visible),
  - switching persona / "show me the evidence" RE-RENDERS the latest snapshot
    with NO new LLM call (facts unchanged, only the lens),
  - every reply ships its evidence so "show me the evidence" is always available.

The LLM is a fake (canned JSON) and the data source is the deterministic
ReplayAdapter — fully offline, no key, no spend.
"""
import json

from app.config import Settings
from app.copilot import CopilotSession, _build_source, build_default_session
from app.reasoning.engine import ReasoningEngine
from app.reasoning.evidence import build_evidence_catalog
from app.telemetry.datadog import LiveDatadogAdapter
from app.telemetry.replay import ReplayAdapter
from app.workspace.store import WorkspaceStore

_DEFAULT_ENV = [
    "ANTHROPIC_API_KEY", "DATADOG_API_KEY", "DATADOG_APP_KEY",
    "COPILOT_DATA_SOURCE", "COPILOT_WORKSPACE_DB",
]


def _clear(monkeypatch):
    for var in _DEFAULT_ENV:
        monkeypatch.delenv(var, raising=False)


class FakeLLM:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls = 0

    def complete(self, system: str, user: str, deep: bool = False) -> str:
        self.calls += 1
        return json.dumps(self._payload)


def _payload(evidence_id: str) -> dict:
    return {
        "summary": "Checkout latency rose ~10 minutes after the 09:02 deploy.",
        "facts": [
            {"claim": "API p95 latency exceeded the SLO.", "confidence": "high",
             "evidence": [evidence_id]}
        ],
        "hypotheses": [
            {"statement": "The 09:02 deployment caused the latency regression.",
             "confidence": "medium", "supporting_evidence": [evidence_id],
             "contradicting_evidence": [], "missing_information": ["DB pool metrics"]}
        ],
        "recommendations": [
            {"claim": "Roll back the 09:02 deployment.", "confidence": "medium", "evidence": []}
        ],
        "unknowns": [
            {"claim": "Cross-service blast radius is unknown.", "confidence": "low", "evidence": []}
        ],
    }


def build_session():
    source = ReplayAdapter()
    catalog, _ = build_evidence_catalog(source)
    valid_id = next(iter(catalog))
    llm = FakeLLM(_payload(valid_id))
    engine = ReasoningEngine(source, llm)
    store = WorkspaceStore(":memory:")
    session = CopilotSession(source, engine, store, incident_id="replay-demo")
    return session, llm, store, valid_id


def test_ask_creates_workspace_and_records_a_snapshot():
    session, _llm, store, _ = build_session()
    session.ask("Why is checkout slow?", "sre")
    latest = store.latest(session.workspace_id)
    assert latest is not None
    assert latest.seq == 1
    assert "Checkout latency rose" in latest.investigation.summary


def test_second_ask_appends_history():
    session, _llm, store, _ = build_session()
    session.ask("Why is checkout slow?", "sre")
    session.ask("What changed?", "sre")
    history = store.history(session.workspace_id)
    assert len(history) == 2
    assert [h.seq for h in history] == [1, 2]


def test_ask_returns_persona_reply_with_evidence():
    session, _llm, _store, valid_id = build_session()
    result = session.ask("Why is checkout slow?", "sre")
    assert result["persona"] == "sre"
    assert result["reply"]
    ids = {e["id"] for e in result["evidence"]}
    assert valid_id in ids  # evidence ships with every reply


def test_rerender_switches_persona_without_calling_the_llm():
    session, llm, _store, _ = build_session()
    session.ask("Why is checkout slow?", "sre")
    assert llm.calls == 1
    result = session.rerender("leadership")
    assert llm.calls == 1                     # no new investigation
    assert result["persona"] == "leadership"  # re-rendered through a new lens


def test_rerender_with_no_prior_investigation_runs_one():
    session, llm, store, _ = build_session()
    result = session.rerender("pm")
    assert llm.calls == 1
    assert store.latest(session.workspace_id) is not None
    assert result["persona"] == "pm"


def test_artifact_serializes_from_latest_snapshot_without_calling_llm():
    session, llm, _store, _ = build_session()
    session.ask("Why is checkout slow?", "sre")
    assert llm.calls == 1
    result = session.artifact("incident_summary")
    assert llm.calls == 1                       # artifact is a transform, not new reasoning
    assert result["artifact"]["key"] == "incident_summary"
    assert "Checkout latency rose" in result["markdown"]


def test_artifact_with_no_prior_investigation_runs_one():
    session, llm, _store, _ = build_session()
    result = session.artifact("incident_summary")
    assert llm.calls == 1
    assert result["artifact"]["key"] == "incident_summary"


# --- the production factory (build_default_session / _build_source) ---------

def test_build_default_session_is_none_without_key(monkeypatch):
    _clear(monkeypatch)
    assert build_default_session(Settings()) is None


def test_build_default_session_builds_replay_session_with_key(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")  # no network at construction
    monkeypatch.setenv("COPILOT_DATA_SOURCE", "replay")
    monkeypatch.setenv("COPILOT_WORKSPACE_DB", ":memory:")
    session = build_default_session(Settings())
    assert isinstance(session, CopilotSession)
    # workspace_id is created lazily against the replay source
    assert session._source.source_type == "replay"


def test_build_source_selects_replay_by_default(monkeypatch):
    _clear(monkeypatch)
    assert isinstance(_build_source(Settings()), ReplayAdapter)


def test_build_source_selects_datadog_when_configured(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("COPILOT_DATA_SOURCE", "datadog")
    monkeypatch.setenv("DATADOG_API_KEY", "dd-api")
    monkeypatch.setenv("DATADOG_APP_KEY", "dd-app")
    assert isinstance(_build_source(Settings()), LiveDatadogAdapter)


def test_build_source_falls_back_to_replay_when_datadog_keys_missing(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("COPILOT_DATA_SOURCE", "datadog")  # but no DD keys
    assert isinstance(_build_source(Settings()), ReplayAdapter)
