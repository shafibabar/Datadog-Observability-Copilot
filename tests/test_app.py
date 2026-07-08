"""Tests for the FastAPI app surface (app/main.py): status, the conversation
API, keyless degradation, and lazy service construction."""
import json

import pytest
from fastapi.testclient import TestClient

from app.copilot import Copilot
from app.main import app
from app.reasoning.engine import ReasoningEngine
from app.reasoning.evidence import build_evidence_catalog
from app.telemetry.replay import ReplayAdapter
from app.workspace.store import WorkspaceStore

client = TestClient(app)


class _FakeLLM:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def complete(self, system: str, user: str, deep: bool = False) -> str:
        return json.dumps(self._payload)


@pytest.fixture
def wired():
    """Inject a fully offline Copilot (fake LLM + replay) into the app, then tear
    it down so other tests see the keyless default path."""
    source = ReplayAdapter()
    catalog, _ = build_evidence_catalog(source)
    valid_id = next(iter(catalog))
    payload = {
        "summary": "Checkout latency rose after the 09:02 deploy.",
        "facts": [{"claim": "p95 exceeded SLO.", "confidence": "high", "evidence": [valid_id]}],
        "hypotheses": [{"statement": "The deploy caused it.", "confidence": "medium",
                        "supporting_evidence": [valid_id], "contradicting_evidence": [],
                        "missing_information": []}],
        "recommendations": [{"claim": "Roll back.", "confidence": "medium", "evidence": []}],
        "unknowns": [],
    }
    engine = ReasoningEngine(source, _FakeLLM(payload))
    app.state.copilot = Copilot(source, engine, WorkspaceStore(":memory:"), incident_id="t")
    yield valid_id
    app.state.copilot = None


def _new_conversation() -> str:
    return client.post("/api/conversations", json={}).json()["id"]


# --- static surface --------------------------------------------------------

def test_healthz_ok():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_status_endpoint_shape_and_secret_free():
    data = client.get("/api/status").json()
    for key in ["data_source", "anthropic_configured", "datadog_configured",
                "model_fast", "model_deep", "datadog_site"]:
        assert key in data
    assert "api_key" not in data and "app_key" not in data


def test_index_page_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Observability Copilot" in r.text


# --- conversation API (wired) ----------------------------------------------

def test_create_and_list_conversations(wired):
    assert client.get("/api/conversations").json()["conversations"] == []
    cid = _new_conversation()
    convos = client.get("/api/conversations").json()["conversations"]
    assert [c["id"] for c in convos] == [cid]


def test_chat_investigates_and_returns_live_workspace(wired):
    valid_id = wired
    cid = _new_conversation()
    r = client.post(f"/api/conversations/{cid}/chat",
                    json={"message": "Why is checkout slow?", "persona": "sre"})
    assert r.status_code == 200
    data = r.json()
    assert data["persona"] == "sre"
    assert "Checkout latency rose" in data["reply"]
    assert any(e["id"] == valid_id for e in data["evidence"])
    assert data["workspace"]["has_investigation"] is True
    assert data["workspace"]["sections"]


def test_messages_persist_and_reload(wired):
    cid = _new_conversation()
    client.post(f"/api/conversations/{cid}/chat", json={"message": "Why slow?", "persona": "sre"})
    convo = client.get(f"/api/conversations/{cid}").json()
    assert [m["role"] for m in convo["messages"]] == ["user", "assistant"]
    # Subject is derived from the investigation summary, not the raw question.
    assert convo["title"].startswith("Checkout latency")


def test_chat_empty_message_rerenders(wired):
    cid = _new_conversation()
    client.post(f"/api/conversations/{cid}/chat", json={"message": "Why slow?", "persona": "sre"})
    r = client.post(f"/api/conversations/{cid}/chat", json={"message": "", "persona": "leadership"})
    assert r.status_code == 200
    assert r.json()["persona"] == "leadership"


def test_chat_blocks_offtopic_message(wired):
    cid = _new_conversation()
    r = client.post(f"/api/conversations/{cid}/chat",
                    json={"message": "tell me a joke about cats", "persona": "sre"})
    assert r.status_code == 200                     # handled, not an error
    body = r.json()
    assert body["blocked"] is True
    assert "Observability Copilot" in body["reply"]
    # the off-topic prompt was not persisted into the conversation
    convo = client.get(f"/api/conversations/{cid}").json()
    assert convo["messages"] == []


def _scope_body(**over):
    body = {"environments": ["prod"], "tenants": ["acme"],
            "start": "2026-07-01T00:00:00Z", "end": "2026-07-01T01:00:00Z"}
    body.update(over)
    return body


def test_chat_accepts_and_persists_scope(wired):
    cid = _new_conversation()
    r = client.post(f"/api/conversations/{cid}/chat",
                    json={"message": "Why slow?", "persona": "sre", "scope": _scope_body()})
    assert r.status_code == 200
    convo = client.get(f"/api/conversations/{cid}").json()
    assert convo["scope"]["environments"] == ["prod"]


def test_chat_rejects_scope_with_no_selection(wired):
    cid = _new_conversation()
    r = client.post(f"/api/conversations/{cid}/chat",
                    json={"message": "Why slow?", "persona": "sre",
                          "scope": _scope_body(environments=[], tenants=[])})
    assert r.status_code == 400
    assert "environment or tenant" in r.json()["error"]


def test_chat_rejects_scope_over_seven_days(wired):
    cid = _new_conversation()
    r = client.post(f"/api/conversations/{cid}/chat",
                    json={"message": "Why slow?", "persona": "sre",
                          "scope": _scope_body(end="2026-07-30T00:00:00Z")})
    assert r.status_code == 400


def test_scopes_endpoint_lists_environments_and_tenants(wired):
    data = client.get("/api/scopes").json()
    assert data["environments"] and data["tenants"]        # replay's static set
    assert "production" in data["environments"]


def test_rename_conversation_endpoint(wired):
    cid = _new_conversation()
    r = client.patch(f"/api/conversations/{cid}", json={"title": "Checkout incident"})
    assert r.status_code == 200
    assert client.get(f"/api/conversations/{cid}").json()["title"] == "Checkout incident"


def test_rename_unknown_conversation_is_404(wired):
    assert client.patch("/api/conversations/nope", json={"title": "x"}).status_code == 404


def test_delete_conversation_endpoint(wired):
    cid = _new_conversation()
    client.post(f"/api/conversations/{cid}/chat", json={"message": "Why slow?", "persona": "sre"})
    assert client.delete(f"/api/conversations/{cid}").status_code == 200
    assert client.get(f"/api/conversations/{cid}").status_code == 404


def test_delete_unknown_conversation_is_404(wired):
    assert client.delete("/api/conversations/nope").status_code == 404


def test_artifact_endpoint_generates_incident_summary(wired):
    cid = _new_conversation()
    client.post(f"/api/conversations/{cid}/chat", json={"message": "Why slow?", "persona": "sre"})
    r = client.post(f"/api/conversations/{cid}/artifact", json={"key": "incident_summary"})
    assert r.status_code == 200
    assert "Checkout latency rose" in r.json()["markdown"]


def test_artifact_endpoint_rejects_unknown_key(wired):
    cid = _new_conversation()
    r = client.post(f"/api/conversations/{cid}/artifact", json={"key": "nope"})
    assert r.status_code == 400


def test_unknown_conversation_is_404(wired):
    assert client.get("/api/conversations/nope").status_code == 404
    assert client.post("/api/conversations/nope/chat",
                       json={"message": "hi", "persona": "sre"}).status_code == 404
    assert client.post("/api/conversations/nope/artifact",
                       json={"key": "incident_summary"}).status_code == 404


# --- degradation when no LLM backend is available --------------------------
# (no API key AND no `claude` CLI). build_copilot returns None in that case;
# we force it here so the path is deterministic regardless of the environment.

def test_listing_reports_unconfigured_without_backend(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "build_copilot", lambda _s: None)
    main.app.state.copilot = None
    data = client.get("/api/conversations").json()
    assert data["configured"] is False
    assert data["conversations"] == []


def test_mutating_endpoints_503_without_backend(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "build_copilot", lambda _s: None)
    main.app.state.copilot = None
    assert client.post("/api/conversations", json={}).status_code == 503
    assert client.post("/api/conversations/x/chat",
                       json={"message": "hi"}).status_code == 503


def test_copilot_is_lazily_built_and_cached(monkeypatch):
    """With a key configured, the first request builds the service from settings
    and caches it on app.state for reuse."""
    import app.main as main

    built = []

    def fake_build(_settings):
        built.append(1)
        source = ReplayAdapter()
        engine = ReasoningEngine(source, _FakeLLM({
            "summary": "ok", "facts": [], "hypotheses": [],
            "recommendations": [], "unknowns": [],
        }))
        return Copilot(source, engine, WorkspaceStore(":memory:"), incident_id="t")

    monkeypatch.setattr(main, "build_copilot", fake_build)
    main.app.state.copilot = None
    client.get("/api/conversations")
    client.get("/api/conversations")
    assert built == [1]  # built once, then cached
    main.app.state.copilot = None
