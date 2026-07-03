"""Spec for the conversation-aware Copilot orchestrator.

A conversation = a Workspace (living investigation) + its message history, both
persisted. The Copilot manages multiple independent conversations:
  - asking a question persists the turn, investigates WITH prior turns as memory,
    appends a snapshot, and persists the reply,
  - persona switch re-renders the latest snapshot with NO new LLM call,
  - conversations are isolated and survive being listed/switched,
  - every reply ships evidence + the serialized live Workspace.

The LLM is a fake (canned JSON) and the data source is the deterministic
ReplayAdapter — fully offline, no key, no spend.
"""
import json

from app.config import Settings
from app.copilot import Copilot, _build_source, build_copilot
from app.reasoning.engine import ReasoningEngine
from app.reasoning.evidence import build_evidence_catalog
from app.telemetry.datadog import LiveDatadogAdapter
from app.telemetry.replay import ReplayAdapter
from app.workspace.store import WorkspaceStore

_DEFAULT_ENV = [
    "ANTHROPIC_API_KEY", "DATADOG_API_KEY", "DATADOG_APP_KEY", "DATADOG_ACCESS_TOKEN",
    "COPILOT_DATA_SOURCE", "COPILOT_WORKSPACE_DB", "COPILOT_LLM_BACKEND",
]


def _clear(monkeypatch):
    for var in _DEFAULT_ENV:
        monkeypatch.delenv(var, raising=False)


class FakeLLM:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls = 0
        self.last_prompt = None

    def complete(self, system: str, user: str, deep: bool = False) -> str:
        self.calls += 1
        self.last_prompt = user
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


def build_copilot_under_test():
    source = ReplayAdapter()
    catalog, _ = build_evidence_catalog(source)
    valid_id = next(iter(catalog))
    llm = FakeLLM(_payload(valid_id))
    engine = ReasoningEngine(source, llm)
    store = WorkspaceStore(":memory:")
    return Copilot(source, engine, store, incident_id="replay-demo"), llm, store, valid_id


# --- conversation lifecycle ------------------------------------------------

def test_new_conversation_appears_in_listing():
    cp, _llm, _store, _ = build_copilot_under_test()
    cid = cp.new_conversation()
    convos = cp.list_conversations()
    assert [c["id"] for c in convos] == [cid]
    assert convos[0]["message_count"] == 0


def test_conversations_are_isolated():
    cp, _llm, _store, _ = build_copilot_under_test()
    a = cp.new_conversation()
    b = cp.new_conversation()
    cp.ask(a, "Why is checkout slow?", "sre")
    msgs_a = cp.get_conversation(a)["messages"]
    msgs_b = cp.get_conversation(b)["messages"]
    assert len(msgs_a) == 2  # user + assistant
    assert len(msgs_b) == 0


# --- the chat loop ---------------------------------------------------------

def test_ask_persists_user_and_assistant_turns():
    cp, _llm, _store, _ = build_copilot_under_test()
    cid = cp.new_conversation()
    cp.ask(cid, "Why is checkout slow?", "sre")
    msgs = cp.get_conversation(cid)["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "Why is checkout slow?"
    assert "Checkout latency rose" in msgs[1]["content"]


def test_ask_titles_conversation_from_first_question():
    cp, _llm, _store, _ = build_copilot_under_test()
    cid = cp.new_conversation()
    cp.ask(cid, "Why is checkout slow right now?", "sre")
    assert cp.get_conversation(cid)["title"].startswith("Why is checkout slow")


def test_followup_feeds_prior_turns_as_memory():
    cp, llm, _store, _ = build_copilot_under_test()
    cid = cp.new_conversation()
    cp.ask(cid, "Is the system healthy?", "sre")
    cp.ask(cid, "What changed after that?", "sre")
    # The 2nd investigation's prompt must carry the earlier exchange.
    assert "Is the system healthy?" in llm.last_prompt
    assert "What changed after that?" in llm.last_prompt


def test_ask_returns_reply_evidence_and_live_workspace():
    cp, _llm, _store, valid_id = build_copilot_under_test()
    cid = cp.new_conversation()
    result = cp.ask(cid, "Why is checkout slow?", "sre")
    assert result["persona"] == "sre"
    assert result["reply"]
    assert any(e["id"] == valid_id for e in result["evidence"])
    assert result["workspace"]["has_investigation"] is True
    assert result["workspace"]["sections"]              # serialized live document


def test_rerender_switches_persona_without_calling_the_llm():
    cp, llm, _store, _ = build_copilot_under_test()
    cid = cp.new_conversation()
    cp.ask(cid, "Why is checkout slow?", "sre")
    assert llm.calls == 1
    result = cp.rerender(cid, "leadership")
    assert llm.calls == 1
    assert result["persona"] == "leadership"


def test_rerender_with_no_investigation_is_a_noop_view():
    cp, llm, _store, _ = build_copilot_under_test()
    cid = cp.new_conversation()
    result = cp.rerender(cid, "pm")
    assert llm.calls == 0
    assert result["no_investigation"] is True


def test_artifact_serializes_from_latest_without_calling_llm():
    cp, llm, _store, _ = build_copilot_under_test()
    cid = cp.new_conversation()
    cp.ask(cid, "Why is checkout slow?", "sre")
    assert llm.calls == 1
    result = cp.artifact(cid, "incident_summary")
    assert llm.calls == 1
    assert result["artifact"]["key"] == "incident_summary"
    assert "Checkout latency rose" in result["markdown"]


def test_get_conversation_response_is_json_serializable():
    cp, _llm, _store, _ = build_copilot_under_test()
    cid = cp.new_conversation()
    cp.ask(cid, "Why is checkout slow?", "sre")
    json.dumps(cp.get_conversation(cid))  # must not raise


# --- the production factory ------------------------------------------------

def test_build_copilot_is_none_without_any_backend(monkeypatch):
    # No API key AND the claude CLI isn't available -> nothing to reason with.
    _clear(monkeypatch)
    assert build_copilot(Settings(), cli_available=lambda: False) is None


def test_build_copilot_uses_cli_backend_when_keyless_and_cli_present(monkeypatch):
    # The "Claude Code way": no API key, but the local claude CLI is available.
    from app.reasoning.llm import ClaudeCliClient

    _clear(monkeypatch)
    monkeypatch.setenv("COPILOT_WORKSPACE_DB", ":memory:")
    cp = build_copilot(Settings(), cli_available=lambda: True)
    assert isinstance(cp, Copilot)
    assert isinstance(cp._engine._llm, ClaudeCliClient)


def test_build_copilot_sdk_backend_requires_key(monkeypatch):
    # Explicitly asking for the SDK backend with no key degrades gracefully.
    _clear(monkeypatch)
    monkeypatch.setenv("COPILOT_LLM_BACKEND", "sdk")
    assert build_copilot(Settings(), cli_available=lambda: True) is None


def test_build_copilot_builds_replay_with_key(monkeypatch):
    from app.reasoning.llm import AnthropicClient

    _clear(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("COPILOT_DATA_SOURCE", "replay")
    monkeypatch.setenv("COPILOT_WORKSPACE_DB", ":memory:")
    cp = build_copilot(Settings())
    assert isinstance(cp, Copilot)
    # a key present prefers the SDK backend under the default "auto" policy
    assert isinstance(cp._engine._llm, AnthropicClient)


def test_build_source_selects_replay_by_default(monkeypatch):
    _clear(monkeypatch)
    assert isinstance(_build_source(Settings()), ReplayAdapter)


def test_build_source_selects_datadog_when_configured(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("COPILOT_DATA_SOURCE", "datadog")
    monkeypatch.setenv("DATADOG_API_KEY", "dd-api")
    monkeypatch.setenv("DATADOG_APP_KEY", "dd-app")
    assert isinstance(_build_source(Settings()), LiveDatadogAdapter)


def test_build_source_selects_datadog_with_access_token(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("COPILOT_DATA_SOURCE", "datadog")
    monkeypatch.setenv("DATADOG_ACCESS_TOKEN", "pat-xyz")
    assert isinstance(_build_source(Settings()), LiveDatadogAdapter)


def test_build_source_falls_back_to_replay_when_keys_missing(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("COPILOT_DATA_SOURCE", "datadog")
    assert isinstance(_build_source(Settings()), ReplayAdapter)
