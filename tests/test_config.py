"""Tests for secure config / secret loading (app/config.py)."""
from app.config import Settings

_SECRET_VARS = [
    "ANTHROPIC_API_KEY",
    "DATADOG_API_KEY",
    "DATADOG_APP_KEY",
    "DATADOG_ACCESS_TOKEN",
    "COPILOT_DATA_SOURCE",
    "COPILOT_MODEL_FAST",
    "COPILOT_MODEL_DEEP",
    "COPILOT_LLM_BACKEND",
    "DATADOG_SITE",
    "COPILOT_WORKSPACE_DB",
]


def _clear(monkeypatch):
    for var in _SECRET_VARS:
        monkeypatch.delenv(var, raising=False)


def test_defaults_when_unset(monkeypatch):
    _clear(monkeypatch)
    s = Settings()
    assert s.data_source == "replay"
    assert s.has_anthropic is False
    assert s.has_datadog is False
    assert s.datadog_site == "datadoghq.com"
    assert s.model_fast and s.model_deep  # sensible non-empty defaults


def test_anthropic_detected_when_key_present(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    assert Settings().has_anthropic is True


def test_datadog_requires_both_keys(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DATADOG_API_KEY", "dd-api-only")
    assert Settings().has_datadog is False  # app key missing
    monkeypatch.setenv("DATADOG_APP_KEY", "dd-app")
    assert Settings().has_datadog is True


def test_datadog_configured_with_access_token_alone(monkeypatch):
    # A Personal Access Token is a standalone credential — no api/app key needed.
    _clear(monkeypatch)
    monkeypatch.setenv("DATADOG_ACCESS_TOKEN", "pat-abc")
    assert Settings().has_datadog is True


def test_llm_backend_defaults_to_auto_and_is_lowercased(monkeypatch):
    _clear(monkeypatch)
    assert Settings().llm_backend == "auto"
    monkeypatch.setenv("COPILOT_LLM_BACKEND", "CLI")
    assert Settings().llm_backend == "cli"


def test_data_source_is_lowercased(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("COPILOT_DATA_SOURCE", "DataDog")
    assert Settings().data_source == "datadog"


def test_status_never_leaks_secret_values(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-xyz")
    monkeypatch.setenv("DATADOG_API_KEY", "dd-secret-abc")
    monkeypatch.setenv("DATADOG_APP_KEY", "dd-app-secret")
    blob = repr(Settings().status())
    assert "sk-secret-xyz" not in blob
    assert "dd-secret-abc" not in blob
    assert "dd-app-secret" not in blob


def test_status_reports_capability_booleans(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    st = Settings().status()
    assert st["anthropic_configured"] is True
    assert st["datadog_configured"] is False


def test_workspace_db_default_and_override(monkeypatch):
    _clear(monkeypatch)
    assert Settings().workspace_db == "data/workspace.db"
    monkeypatch.setenv("COPILOT_WORKSPACE_DB", "/tmp/custom.db")
    assert Settings().workspace_db == "/tmp/custom.db"
