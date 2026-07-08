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


def _get_bool(name: str, default: bool) -> bool:
    """Parse a boolean env var. Falsey: 0/false/no/off (case-insensitive)."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


@dataclass(frozen=True)
class Settings:
    # Anthropic / Claude
    anthropic_api_key: str = field(default_factory=lambda: _get("ANTHROPIC_API_KEY"))
    model_fast: str = field(default_factory=lambda: _get("COPILOT_MODEL_FAST", "claude-haiku-4-5-20251001"))
    model_deep: str = field(default_factory=lambda: _get("COPILOT_MODEL_DEEP", "claude-sonnet-4-6"))
    # Which LLM backend to use: "auto" (Claude CLI when no key, else SDK), "cli", or "sdk".
    llm_backend: str = field(default_factory=lambda: _get("COPILOT_LLM_BACKEND", "auto").lower())

    # Relevance & abuse guard (pre-reasoning gate). On by default; "hybrid" consults
    # a cheap classifier for the ambiguous middle, "deterministic" refuses it outright.
    guard_enabled: bool = field(default_factory=lambda: _get_bool("COPILOT_GUARD_ENABLED", True))
    guard_mode: str = field(default_factory=lambda: _get("COPILOT_GUARD_MODE", "hybrid").lower())
    guard_max_chars: int = field(default_factory=lambda: int(_get("COPILOT_GUARD_MAX_CHARS", "2000") or "2000"))

    # Datadog (optional — only needed for the live data source)
    datadog_api_key: str = field(default_factory=lambda: _get("DATADOG_API_KEY"))
    datadog_app_key: str = field(default_factory=lambda: _get("DATADOG_APP_KEY"))
    # A Personal Access Token (PAT) is a standalone credential — preferred over the legacy key pair.
    datadog_access_token: str = field(default_factory=lambda: _get("DATADOG_ACCESS_TOKEN"))
    datadog_site: str = field(default_factory=lambda: _get("DATADOG_SITE", "datadoghq.com"))
    # "tenant" is not a native Datadog concept; the tag key that represents it is
    # org-specific, so it's configurable (env is the standard environment tag).
    datadog_tenant_tag: str = field(default_factory=lambda: _get("DATADOG_TENANT_TAG", "tenant"))
    # A widely-emitted metric used only to enumerate distinct env/tenant tag values
    # for the scope dropdowns. Org-specific — must be a metric that carries the tags.
    datadog_discovery_metric: str = field(
        default_factory=lambda: _get("DATADOG_DISCOVERY_METRIC", "system.cpu.user"))

    # App
    data_source: str = field(default_factory=lambda: _get("COPILOT_DATA_SOURCE", "replay").lower())
    workspace_db: str = field(default_factory=lambda: _get("COPILOT_WORKSPACE_DB", "data/workspace.db"))

    # --- Capability checks (never expose the secret values themselves) ---
    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_datadog(self) -> bool:
        # A PAT authenticates on its own; otherwise the legacy pair is required.
        return bool(self.datadog_access_token or (self.datadog_api_key and self.datadog_app_key))

    def status(self) -> dict[str, object]:
        """Safe, secret-free summary for health checks and the UI banner."""
        return {
            "data_source": self.data_source,
            "anthropic_configured": self.has_anthropic,
            "llm_backend": self.llm_backend,
            "datadog_configured": self.has_datadog,
            "datadog_site": self.datadog_site,
            "model_fast": self.model_fast,
            "model_deep": self.model_deep,
        }


settings = Settings()
