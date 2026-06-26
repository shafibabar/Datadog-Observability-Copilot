"""Central configuration and secret loading.

Secrets are read at runtime from environment variables (populated locally from a
gitignored .env file) and are NEVER written to disk by the app, never logged,
and never persisted into the workspace database. This module is the single seam
where secrets enter the system, so swapping .env for Vault/Okta later is a
one-file change.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root if present. override=False means real
# environment variables (e.g. from Vault/CI later) take precedence over the file.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # Anthropic
    anthropic_api_key: str = field(default_factory=lambda: _get("ANTHROPIC_API_KEY"))
    model_fast: str = field(default_factory=lambda: _get("COPILOT_MODEL_FAST", "claude-haiku-4-5-20251001"))
    model_deep: str = field(default_factory=lambda: _get("COPILOT_MODEL_DEEP", "claude-sonnet-4-6"))

    # Datadog (optional — only needed for the live data source)
    datadog_api_key: str = field(default_factory=lambda: _get("DATADOG_API_KEY"))
    datadog_app_key: str = field(default_factory=lambda: _get("DATADOG_APP_KEY"))
    datadog_site: str = field(default_factory=lambda: _get("DATADOG_SITE", "datadoghq.com"))

    # App
    data_source: str = field(default_factory=lambda: _get("COPILOT_DATA_SOURCE", "replay").lower())
    workspace_db: str = field(default_factory=lambda: _get("COPILOT_WORKSPACE_DB", "data/workspace.db"))

    # --- Capability checks (never expose the secret values themselves) ---
    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_datadog(self) -> bool:
        return bool(self.datadog_api_key and self.datadog_app_key)

    def status(self) -> dict[str, object]:
        """Safe, secret-free summary for health checks and the UI banner."""
        return {
            "data_source": self.data_source,
            "anthropic_configured": self.has_anthropic,
            "datadog_configured": self.has_datadog,
            "datadog_site": self.datadog_site,
            "model_fast": self.model_fast,
            "model_deep": self.model_deep,
        }


settings = Settings()
