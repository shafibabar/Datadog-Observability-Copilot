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

from datetime import datetime, timedelta, timezone

from app.artifacts import render_artifact
from app.guard import evaluate as guard_evaluate
from app.personas import get_persona, render
from app.reasoning.engine import ReasoningEngine
from app.telemetry.base import DataSource
from app.telemetry.models import Scope
from app.telemetry.namespaces import filter_queries, parse_patterns
from app.workspace.sections import serialize_sections
from app.workspace.store import WorkspaceStore

_NEW_TITLE = "New investigation"


def _subject_from(summary: str, fallback: str = "") -> str:
    """A short conversation subject derived from the investigation summary (its
    first sentence, trimmed) — a meaningful title with no extra LLM call. Falls
    back to the raw question, then to the default sentinel."""
    text = " ".join((summary or "").split())
    if not text:
        text = " ".join((fallback or "").split())
    for sep in (". ", "; ", " — "):
        i = text.find(sep)
        if i != -1:
            text = text[:i]
            break
    return (text[:48].rstrip() + "…") if len(text) > 48 else (text or _NEW_TITLE)


class Copilot:
    def __init__(
        self,
        source: DataSource,
        engine: ReasoningEngine,
        store: WorkspaceStore,
        incident_id: str = "incident",
        guard_enabled: bool = True,
        guard_mode: str = "hybrid",
        guard_max_chars: int = 2000,
        classifier=None,
        guard_extra_vocabulary: tuple[str, ...] = (),
        default_environments: tuple[str, ...] = (),
        default_tenants: tuple[str, ...] = (),
        default_window_days: int = 2,
    ) -> None:
        self._source = source
        self._engine = engine
        self._store = store
        self._incident_id = incident_id
        self._guard_enabled = guard_enabled
        self._guard_mode = guard_mode
        self._guard_max_chars = guard_max_chars
        self._classifier = classifier
        self._guard_extra_vocabulary = tuple(guard_extra_vocabulary)
        self._default_environments = tuple(default_environments)
        self._default_tenants = tuple(default_tenants)
        self._default_window_days = default_window_days

    # --- conversations -----------------------------------------------------

    def new_conversation(self, title: str = "") -> str:
        return self._store.create_workspace(
            incident_id=self._incident_id,
            source_type=self._source.source_type,
            title=title or _NEW_TITLE,
        )

    def list_conversations(self) -> list[dict]:
        return [c.model_dump(mode="json") for c in self._store.list_conversations()]

    def list_scopes(self, environments: list[str] | None = None) -> dict[str, list[str]]:
        """Environments/tenants selectable for the @ scope menu. When a platform
        scope is configured (COPILOT_PLATFORM_ENVIRONMENTS/_TENANTS), that fixed,
        known list is served directly — no live discovery call, and no narrowing
        by the `environments` filter, since it's already a small known set.
        Otherwise falls back to the live data source's discovery."""
        if self._default_environments or self._default_tenants:
            return {"environments": list(self._default_environments),
                    "tenants": list(self._default_tenants)}
        return self._source.list_scopes(environments)

    def get_conversation(self, cid: str) -> dict:
        meta = self._store.get_workspace(cid)  # raises KeyError if unknown
        scope = self._store.get_scope(cid)
        return {
            "id": cid,
            "title": meta.title,
            "source_type": meta.source_type,
            "scope": scope.model_dump(mode="json") if scope else None,
            "messages": [m.model_dump(mode="json") for m in self._store.get_messages(cid)],
            "workspace": self._workspace_payload(cid),
        }

    def rename(self, cid: str, title: str) -> None:
        self._store.get_workspace(cid)  # validate (raises KeyError) before writing
        self._store.set_title(cid, title.strip() or _NEW_TITLE)

    def delete(self, cid: str) -> None:
        self._store.get_workspace(cid)  # validate (raises KeyError) before deleting
        self._store.delete_workspace(cid)

    # --- the chat loop -----------------------------------------------------

    def ask(self, cid: str, message: str, persona: str, scope=None) -> dict:
        self._store.get_workspace(cid)  # validate (raises KeyError) before writing

        # Pre-reasoning gate: an off-topic / injection message is refused BEFORE
        # anything is persisted or the expensive reasoning path runs.
        if self._guard_enabled:
            verdict = guard_evaluate(
                message,
                has_context=self._store.latest(cid) is not None,
                mode=self._guard_mode,
                max_chars=self._guard_max_chars,
                classifier=self._classifier,
                extra_vocabulary=self._guard_extra_vocabulary,
            )
            if not verdict.allowed:
                return self._blocked_view(cid, persona, verdict)

        # The investigation lens can change per turn; persist the latest one and
        # fall back to whatever was last used on this conversation. Any field
        # left unset (no @ selection made) is backfilled from the configured
        # platform default rather than forcing the user to pick one.
        if scope is not None:
            scope = self._with_defaults(scope)
            self._store.set_scope(cid, scope)
        else:
            scope = self._store.get_scope(cid)
            if scope is None:
                scope = self._with_defaults(None)
                self._store.set_scope(cid, scope)

        # History is the conversation *before* this turn → real follow-up memory.
        history = [(m.role, m.content) for m in self._store.get_messages(cid)]
        self._store.add_message(cid, role="user", content=message, persona=persona)

        investigation = self._engine.investigate(message or None, history=history, scope=scope)
        self._store.record(cid, investigation)

        # Give a brand-new conversation a meaningful subject from the summary.
        meta = self._store.get_workspace(cid)
        if meta.title in ("", _NEW_TITLE):
            self._store.set_title(cid, _subject_from(investigation.summary, message))

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

    def _with_defaults(self, scope: Scope | None) -> Scope:
        """Fill any unset field of `scope` (or build one from scratch) from the
        configured platform default — never errors, never asks the user first."""
        now = datetime.now(timezone.utc)
        environments = (scope.environments if scope else []) or list(self._default_environments)
        tenants = (scope.tenants if scope else []) or list(self._default_tenants)
        start = (scope.start if scope else None) or (now - timedelta(days=self._default_window_days))
        end = (scope.end if scope else None) or now
        return Scope(environments=environments, tenants=tenants, start=start, end=end)

    def _blocked_view(self, cid: str, persona_key: str, verdict) -> dict:
        """The reply for a message the guard refused — no reasoning, nothing
        persisted, the live Workspace left exactly as it was."""
        persona = get_persona(persona_key)
        return {
            "blocked": True,
            "category": verdict.category,
            "reply": verdict.refusal,
            "persona": persona.key,
            "persona_label": persona.label,
            "evidence": [],
            "workspace": self._workspace_payload(cid),
        }

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


def _resolve_backend(settings, cli_available) -> str:
    """Decide which LLM backend to use: 'sdk', 'cli', or 'none' (degrade).

    - sdk : requires an API key.
    - cli : requires the local `claude` CLI (the keyless "Claude Code way").
    - auto: prefer the SDK when a key is present, otherwise fall back to the CLI.
    """
    backend = settings.llm_backend
    if backend == "sdk":
        return "sdk" if settings.has_anthropic else "none"
    if backend == "cli":
        return "cli" if cli_available() else "none"
    # "auto" (default)
    if settings.has_anthropic:
        return "sdk"
    return "cli" if cli_available() else "none"


def build_copilot(settings, cli_available=None) -> Copilot | None:
    """Build the Copilot from runtime settings, or return None when no LLM
    backend is available (no API key and no `claude` CLI) so the app degrades
    gracefully without crashing. `cli_available` is injectable for tests."""
    from app.guard_classifier import classify_relevance
    from app.monitors.index import build_monitors_index, service_vocabulary
    from app.reasoning.llm import cli_available as _detect_cli

    if cli_available is None:
        cli_available = _detect_cli

    backend = _resolve_backend(settings, cli_available)
    if backend == "none":
        return None

    # Monitors knowledge base (empty when MONITORS_REPO_PATH is unset/missing).
    # Built before the source so extracted metric queries can feed the adapter, and
    # scoped to the same metric namespaces the adapter is scoped to.
    monitors_index = build_monitors_index(
        settings.monitors_repo_path, namespaces=settings.datadog_metric_namespaces)

    source = _build_source(settings, monitors_index.metric_queries)
    if backend == "sdk":
        from app.reasoning.llm import AnthropicClient

        llm = AnthropicClient(
            api_key=settings.anthropic_api_key,
            model_fast=settings.model_fast,
            model_deep=settings.model_deep,
        )
    else:  # "cli"
        from app.reasoning.llm import ClaudeCliClient

        llm = ClaudeCliClient(model_fast=settings.model_fast, model_deep=settings.model_deep)

    engine = ReasoningEngine(source, llm, monitors_index=monitors_index)
    store = WorkspaceStore(settings.workspace_db)
    # On-topic vocabulary: the hand-listed COPILOT_PLATFORM_* terms PLUS the service
    # phrases implied by the metrics actually in scope ("ec.quota_manager.x" ->
    # "quota manager"). That second half is what lets a namespace like `ec.*` make
    # hundreds of real service names on-topic with no extra configuration.
    guard_extra_vocabulary = (
        settings.platform_metrics + settings.platform_log_sources
        + settings.platform_trace_services + settings.platform_tenants
        + settings.platform_environments
        + service_vocabulary(source.list_metrics())
    )

    # Stage-2 guard classifier: semantic relevance via the fast model. Errors
    # propagate into guard.evaluate, which fails closed by design.
    def classifier(msg: str) -> bool:
        return classify_relevance(msg, llm)

    return Copilot(
        source, engine, store,
        incident_id=f"{source.source_type}-session",
        guard_enabled=settings.guard_enabled,
        guard_mode=settings.guard_mode,
        guard_max_chars=settings.guard_max_chars,
        guard_extra_vocabulary=guard_extra_vocabulary,
        default_environments=settings.platform_environments,
        default_tenants=settings.platform_tenants,
        default_window_days=settings.platform_default_window_days,
        classifier=classifier,
    )


def merged_metric_queries(
    extracted: dict[str, str] | None,
    configured: dict[str, str] | None,
    discovered: dict[str, str] | None = None,
    namespaces: tuple[str, ...] = (),
) -> dict[str, str] | None:
    """Combine every source of metric queries into the adapter's registry.

    Precedence **configured > extracted > discovered**: an explicit
    DATADOG_METRIC_QUERIES entry always wins; a Terraform-extracted query beats a
    live-discovered one because it carries the real aggregation (`sum:` /
    `.as_count()`) rather than a generic default.

    **Extracted metrics must be confirmed reporting.** When discovery returned
    anything at all, a metric found in the Terraform repo but absent from the live
    list is dropped: the `.tf` files describe monitors that may reference metrics
    no longer emitted (verified live 2026-08-05 — one such metric returned zero
    series and zero tags), and a metric that cannot return data has no business
    being selectable as evidence. When discovery returned nothing (it failed, or
    isn't configured) the full extracted set survives — that's the graceful
    degradation path, not a reason to empty the registry.

    The result is then narrowed to `namespaces` (DATADOG_METRIC_NAMESPACES) — an
    allowlist, so nothing outside the configured scope can be queried — except
    names you configured explicitly, which are a deliberate override.

    Returns None only when NO namespaces are configured and nothing was found, so
    the adapter falls back to its built-in infra defaults. With namespaces set the
    result is always a dict (possibly empty): "only these are in scope" must never
    silently reintroduce `system.*`.
    """
    discovered = dict(discovered or {})
    extracted = dict(extracted or {})
    if discovered:
        extracted = {n: q for n, q in extracted.items() if n in discovered}
    merged = {**discovered, **extracted, **(configured or {})}
    if namespaces:
        return filter_queries(merged, parse_patterns(namespaces), keep=(configured or {}))
    return merged or None


def _build_source(settings, extracted_metric_queries: dict[str, str] | None = None) -> DataSource:
    if settings.data_source == "datadog" and settings.has_datadog:
        from app.telemetry.datadog import (
            LiveDatadogAdapter,
            discover_metric_names,
            discovered_queries,
        )

        credentials = {
            "api_key": settings.datadog_api_key,
            "app_key": settings.datadog_app_key,
            "access_token": settings.datadog_access_token,
            "site": settings.datadog_site,
            "verify": settings.datadog_verify,
        }
        # Ask the org which metrics under the configured namespaces are actually
        # reporting. Best-effort: a failure here yields {} and the registry falls
        # back to whatever Terraform gave us.
        namespaces = settings.datadog_metric_namespaces
        discovered = discovered_queries(discover_metric_names(namespaces, **credentials))
        return LiveDatadogAdapter(
            tenant_tag=settings.datadog_tenant_tag,
            env_tag=settings.datadog_env_tag,
            metric_queries=merged_metric_queries(
                extracted_metric_queries,
                settings.datadog_metric_queries,
                discovered=discovered,
                namespaces=namespaces,
            ),
            **credentials,
        )
    from app.telemetry.replay import ReplayAdapter

    return ReplayAdapter()
