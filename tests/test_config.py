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
    "COPILOT_GUARD_ENABLED",
    "COPILOT_GUARD_MODE",
    "COPILOT_GUARD_MAX_CHARS",
    "DATADOG_SITE",
    "DATADOG_CA_BUNDLE",
    "DATADOG_VERIFY_SSL",
    "DATADOG_METRIC_QUERIES",
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


def test_guard_defaults_on_and_hybrid(monkeypatch):
    _clear(monkeypatch)
    s = Settings()
    assert s.guard_enabled is True             # protection on by default
    assert s.guard_mode == "hybrid"
    assert s.guard_max_chars > 0


def test_guard_can_be_disabled_and_mode_overridden(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("COPILOT_GUARD_ENABLED", "0")
    monkeypatch.setenv("COPILOT_GUARD_MODE", "Deterministic")
    s = Settings()
    assert s.guard_enabled is False
    assert s.guard_mode == "deterministic"


def test_status_reports_dotenv_diagnostics_without_secrets(monkeypatch):
    _clear(monkeypatch)
    s = Settings().status()
    assert s["dotenv_path"].endswith(".env")     # where the app looks for it
    assert "dotenv_loaded" in s                    # whether a file was found
    # diagnostics must stay secret-free
    assert "api_key" not in s and "app_key" not in s and "access_token" not in s


def test_datadog_tls_defaults_to_verifying(monkeypatch):
    _clear(monkeypatch)
    s = Settings()
    assert s.datadog_ca_bundle == ""
    assert s.datadog_verify_ssl is True
    assert s.datadog_verify is True          # httpx verify: on by default


def test_datadog_ca_bundle_becomes_the_verify_path(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DATADOG_CA_BUNDLE", "/etc/ssl/corp-root.pem")
    assert Settings().datadog_verify == "/etc/ssl/corp-root.pem"


def test_datadog_verify_can_be_disabled(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DATADOG_VERIFY_SSL", "0")
    s = Settings()
    assert s.datadog_verify_ssl is False
    assert s.datadog_verify is False


def test_datadog_metric_queries_default_none_and_parsed(monkeypatch):
    _clear(monkeypatch)
    assert Settings().datadog_metric_queries is None      # falls back to adapter defaults
    monkeypatch.setenv("DATADOG_METRIC_QUERIES", '{"cpu": "avg:system.cpu.user{*}"}')
    assert Settings().datadog_metric_queries == {"cpu": "avg:system.cpu.user{*}"}


def test_datadog_metric_queries_bad_json_is_ignored(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DATADOG_METRIC_QUERIES", "{not valid json")
    assert Settings().datadog_metric_queries is None      # tolerant: never crashes startup


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
