"""Tests for the FastAPI app surface (app/main.py)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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
