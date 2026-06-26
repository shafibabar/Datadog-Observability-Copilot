"""Copilot — the conversation-aware orchestrator.

Joins a DataSource, the ReasoningEngine, and persisted state into the chat loop,
and manages *multiple independent conversations*. A conversation is a Workspace
(its living investigation) plus its message history; both are persisted, so
conversations survive a restart and can be listed and switched between.

  - `ask(cid, message, persona)` persists the user turn, investigates WITH the
    recent conversation history as context (real follow-up memory), appends a
    Workspace snapshot, persists the assistant turn, and returns the rendered
    reply + the live Workspace view.
  - `rerender(cid, persona)` re-renders the latest snapshot through a different
    lens with NO new reasoning (facts unchanged, only the lens).
  - `artifact(cid, key)` serializes an operational artifact from the latest
    snapshot (a pure transform).

Every reply ships its evidence and the serialized Workspace sections, so the UI
can show the living document beside the chat and "show me the evidence" is
always available.
"""
from __future__ import annotations

from app.artifacts import render_artifact
from app.personas import get_persona, render
from app.reasoning.engine import ReasoningEngine
from app.telemetry.base import DataSource
from app.workspace.sections import serialize_sections
from app.workspace.store import WorkspaceStore

_NEW_TITLE = "New investigation"


def _title_from(message: str) -> str:
    """A short, single-line conversation title derived from the first question."""
    line = " ".join((message or "").split())
    return (line[:48] + "…") if len(line) > 48 else (line or _NEW_TITLE)


class Copilot:
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

    # --- conversations -----------------------------------------------------

    def new_conversation(self, title: str = "") -> str:
        return self._store.create_workspace(
            incident_id=self._incident_id,
            source_type=self._source.source_type,
            title=title or _NEW_TITLE,
        )

    def list_conversations(self) -> list[dict]:
        return [c.model_dump(mode="json") for c in self._store.list_conversations()]

    def get_conversation(self, cid: str) -> dict:
        meta = self._store.get_workspace(cid)  # raises KeyError if unknown
        return {
            "id": cid,
            "title": meta.title,
            "source_type": meta.source_type,
            "messages": [m.model_dump(mode="json") for m in self._store.get_messages(cid)],
            "workspace": self._workspace_payload(cid),
        }

    # --- the chat loop -----------------------------------------------------

    def ask(self, cid: str, message: str, persona: str) -> dict:
        self._store.get_workspace(cid)  # validate (raises KeyError) before writing
        # History is the conversation *before* this turn → real follow-up memory.
        history = [(m.role, m.content) for m in self._store.get_messages(cid)]
        self._store.add_message(cid, role="user", content=message, persona=persona)

        meta = self._store.get_workspace(cid)
        if meta.title in ("", _NEW_TITLE):
            self._store.set_title(cid, _title_from(message))

        investigation = self._engine.investigate(message or None, history=history)
        self._store.record(cid, investigation)

        view = self._view(cid, persona)
        self._store.add_message(cid, role="assistant", content=view["reply"], persona=persona)
        return view

    def rerender(self, cid: str, persona: str) -> dict:
        """Re-render the latest snapshot through a new lens — no LLM call. If
        nothing has been investigated yet, there is nothing to re-frame."""
        self._store.get_workspace(cid)  # validate (raises KeyError) for a 404
        if self._store.latest(cid) is None:
            return {
                "reply": "", "persona": get_persona(persona).key,
                "persona_label": get_persona(persona).label,
                "evidence": [], "no_investigation": True,
                "workspace": self._workspace_payload(cid),
            }
        return self._view(cid, persona)

    def artifact(self, cid: str, key: str) -> dict:
        self._store.get_workspace(cid)  # validate (raises KeyError) before work
        if self._store.latest(cid) is None:
            self._store.record(cid, self._engine.investigate(None))
        snapshot = self._store.latest(cid)
        doc = render_artifact(key, snapshot.investigation, incident_id=self._incident_id)
        return {"artifact": doc.model_dump(), "markdown": doc.to_markdown()}

    # --- internals ---------------------------------------------------------

    def _view(self, cid: str, persona_key: str) -> dict:
        snapshot = self._store.latest(cid)
        inv = snapshot.investigation
        persona = get_persona(persona_key)
        return {
            "reply": render(persona, inv),
            "persona": persona.key,
            "persona_label": persona.label,
            "snapshot_seq": snapshot.seq,
            "evidence": [e.model_dump() for e in inv.evidence.values()],
            "workspace": self._workspace_payload(cid),
        }

    def _workspace_payload(self, cid: str) -> dict:
        snapshot = self._store.latest(cid)
        if snapshot is None:
            return {"has_investigation": False, "sections": []}
        return {
            "has_investigation": True,
            "snapshot_seq": snapshot.seq,
            "sections": serialize_sections(snapshot.investigation),
        }


def build_copilot(settings) -> Copilot | None:
    """Build the Copilot from runtime settings, or return None when Claude is not
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
    return Copilot(source, engine, store, incident_id=f"{source.source_type}-session")


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
