"""CopilotSession — the orchestrator that joins the layers into the chat loop.

A session owns one Investigation Workspace and ties together a DataSource, the
ReasoningEngine, and persona rendering:

  - `ask(message, persona)` runs a genuine investigation over the telemetry and
    APPENDS a snapshot (the living Workspace grows; prior reasoning stays
    visible), then renders the latest state through the persona.
  - `rerender(persona)` re-renders the latest snapshot through a different lens
    with NO new LLM call — switching persona or "show me the evidence" must not
    change the facts (kickoff §5.1). If nothing has been investigated yet, it
    runs a default investigation first.

Every reply ships its evidence catalog and section views, so "show me the
evidence" is a first-class, always-available action (kickoff §5.8/§6.7).
"""
from __future__ import annotations

from app.artifacts import render_artifact
from app.personas import get_persona, render
from app.reasoning.engine import ReasoningEngine
from app.telemetry.base import DataSource
from app.workspace.sections import render_sections
from app.workspace.store import WorkspaceStore


class CopilotSession:
    def __init__(
        self,
        source: DataSource,
        engine: ReasoningEngine,
        store: WorkspaceStore,
        incident_id: str = "incident",
    ) -> None:
        self._source = source
        self._engine = engine
        self._store = store
        self._incident_id = incident_id
        self._workspace_id: str | None = None

    @property
    def workspace_id(self) -> str:
        if self._workspace_id is None:
            self._workspace_id = self._store.create_workspace(
                incident_id=self._incident_id,
                source_type=self._source.source_type,
            )
        return self._workspace_id

    def ask(self, message: str, persona: str) -> dict:
        investigation = self._engine.investigate(message or None)
        self._store.record(self.workspace_id, investigation)
        return self._view(persona)

    def rerender(self, persona: str) -> dict:
        if self._store.latest(self.workspace_id) is None:
            return self.ask("", persona)
        return self._view(persona)

    def artifact(self, key: str) -> dict:
        """Serialize an operational artifact from the latest snapshot (a pure
        transform — no new reasoning). Investigates first if nothing exists yet."""
        if self._store.latest(self.workspace_id) is None:
            self.ask("", "sre")
        snapshot = self._store.latest(self.workspace_id)
        doc = render_artifact(key, snapshot.investigation, incident_id=self._incident_id)
        return {"artifact": doc.model_dump(), "markdown": doc.to_markdown()}

    def _view(self, persona_key: str) -> dict:
        snapshot = self._store.latest(self.workspace_id)
        inv = snapshot.investigation
        persona = get_persona(persona_key)
        return {
            "reply": render(persona, inv),
            "persona": persona.key,
            "persona_label": persona.label,
            "snapshot_seq": snapshot.seq,
            "evidence": [e.model_dump() for e in inv.evidence.values()],
            "sections": [
                {"key": v.key, "title": v.title, "order": v.order}
                for v in render_sections(inv)
            ],
        }


def build_default_session(settings) -> CopilotSession | None:
    """Build a session from runtime settings, or return None when Claude is not
    configured (no key) so the app degrades gracefully without crashing."""
    if not settings.has_anthropic:
        return None

    from app.reasoning.llm import AnthropicClient

    source = _build_source(settings)
    llm = AnthropicClient(
        api_key=settings.anthropic_api_key,
        model_fast=settings.model_fast,
        model_deep=settings.model_deep,
    )
    engine = ReasoningEngine(source, llm)
    store = WorkspaceStore(settings.workspace_db)
    return CopilotSession(source, engine, store, incident_id=f"{source.source_type}-session")


def _build_source(settings) -> DataSource:
    if settings.data_source == "datadog" and settings.has_datadog:
        from app.telemetry.datadog import LiveDatadogAdapter

        return LiveDatadogAdapter(
            api_key=settings.datadog_api_key,
            app_key=settings.datadog_app_key,
            site=settings.datadog_site,
        )
    from app.telemetry.replay import ReplayAdapter

    return ReplayAdapter()
