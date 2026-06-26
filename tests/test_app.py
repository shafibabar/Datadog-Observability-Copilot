"""Tests for the FastAPI app surface (app/main.py)."""
import json

import pytest
from fastapi.testclient import TestClient

from app.copilot import CopilotSession
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
def wired_session():
    """Inject a fully offline CopilotSession (fake LLM + replay) into the app,
    then tear it down so other tests see the keyless default path."""
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
    session = CopilotSession(source, engine, WorkspaceStore(":memory:"), incident_id="t")
    app.state.session = session
    yield valid_id
    app.state.session = None


def test_healthz_ok():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_status_endpoint_shape_and_secret_free():
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    for key in [
        "data_source",
        "anthropic_configured",
        "datadog_configured",
        "model_fast",
        "model_deep",
        "datadog_site",
    ]:
        assert key in data
    # The endpoint must never expose raw secret material.
    assert "api_key" not in data
    assert "app_key" not in data


def test_index_page_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Observability Copilot" in r.text


def test_chat_echoes_persona():
    r = client.post("/api/chat", json={"message": "hi", "persona": "pm"})
    assert r.status_code == 200
    data = r.json()
    assert data["persona"] == "pm"
    assert data.get("reply")


def test_chat_defaults_to_sre_persona():
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 200
    assert r.json()["persona"] == "sre"


def test_chat_investigates_when_session_wired(wired_session):
    valid_id = wired_session
    r = client.post("/api/chat", json={"message": "Why is checkout slow?", "persona": "sre"})
    assert r.status_code == 200
    data = r.json()
    assert data["persona"] == "sre"
    assert "Checkout latency rose" in data["reply"]
    assert any(e["id"] == valid_id for e in data["evidence"])


def test_chat_empty_message_rerenders_persona(wired_session):
    # Seed an investigation, then switch persona with an empty message → re-render.
    client.post("/api/chat", json={"message": "Why slow?", "persona": "sre"})
    r = client.post("/api/chat", json={"message": "", "persona": "leadership"})
    assert r.status_code == 200
    assert r.json()["persona"] == "leadership"
