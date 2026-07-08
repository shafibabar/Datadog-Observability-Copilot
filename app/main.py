"""FastAPI entry point for the Observability Copilot.

Boots the app, serves the UI, exposes a secret-free status endpoint, and wires a
conversation-scoped API to a Copilot service (DataSource + ReasoningEngine +
persisted Workspace + persona rendering). The service is built lazily from
runtime settings; when no Anthropic key is configured the API degrades
gracefully instead of crashing, so the app still runs for a non-developer before
keys are placed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings
from app.copilot import Copilot, build_copilot
from app.telemetry.models import Scope

_WEB = Path(__file__).resolve().parent / "web"
_INDEX = _WEB / "templates" / "index.html"

app = FastAPI(title="Observability Copilot", version="0.2.0")
app.mount("/static", StaticFiles(directory=_WEB / "static"), name="static")

_NOT_CONFIGURED = {
    "error": "Claude isn't configured yet. Either sign in to the Claude Code CLI "
             "(run `claude` once and log in), or add ANTHROPIC_API_KEY to a local "
             ".env file, then restart to enable evidence-backed investigations.",
    "configured": False,
}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> JSONResponse:
    """Secret-free runtime status — drives the UI banner."""
    return JSONResponse(settings.status())


def _get_copilot() -> Copilot | None:
    """Return the active Copilot, building one lazily from settings. Tests may
    pre-set `app.state.copilot` to inject an offline (fake-LLM) service."""
    copilot = getattr(app.state, "copilot", None)
    if copilot is not None:
        return copilot
    copilot = build_copilot(settings)
    if copilot is not None:
        app.state.copilot = copilot
    return copilot


# --- conversations ---------------------------------------------------------

class NewConversationRequest(BaseModel):
    title: str = ""


class ChatRequest(BaseModel):
    message: str
    persona: str = "sre"
    scope: Scope | None = None


class ArtifactRequest(BaseModel):
    key: str = "incident_summary"


class RenameRequest(BaseModel):
    title: str


def _clamp_scope(scope: Scope | None) -> Scope | None:
    """Enforce 'end ≤ now' server-side (the calendar does the same client-side),
    so a window can never reach into the future regardless of the client clock."""
    if scope is None or scope.end is None:
        return scope
    now = datetime.now(timezone.utc)
    if scope.end > now:
        return scope.model_copy(update={"end": now})
    return scope


@app.get("/api/scopes")
def scopes(environments: str = "") -> JSONResponse:
    """Selectable environments/tenants for the scope dropdowns. `environments` is
    an optional comma-separated filter that narrows the tenant list."""
    copilot = _get_copilot()
    if copilot is None:
        return JSONResponse({"environments": [], "tenants": [], **_NOT_CONFIGURED}, status_code=503)
    selected = [e for e in (environments.split(",") if environments else []) if e.strip()]
    return JSONResponse(copilot.list_scopes(selected or None))


@app.get("/api/conversations")
def list_conversations() -> JSONResponse:
    copilot = _get_copilot()
    if copilot is None:
        return JSONResponse({"conversations": [], **_NOT_CONFIGURED})
    return JSONResponse({"conversations": copilot.list_conversations(), "configured": True})


@app.post("/api/conversations")
def create_conversation(req: NewConversationRequest) -> JSONResponse:
    copilot = _get_copilot()
    if copilot is None:
        return JSONResponse(_NOT_CONFIGURED, status_code=503)
    cid = copilot.new_conversation(req.title)
    return JSONResponse(copilot.get_conversation(cid), status_code=201)


@app.get("/api/conversations/{cid}")
def get_conversation(cid: str) -> JSONResponse:
    copilot = _get_copilot()
    if copilot is None:
        return JSONResponse(_NOT_CONFIGURED, status_code=503)
    try:
        return JSONResponse(copilot.get_conversation(cid))
    except KeyError:
        return JSONResponse({"error": f"Unknown conversation: {cid!r}"}, status_code=404)


@app.post("/api/conversations/{cid}/chat")
def chat(cid: str, req: ChatRequest) -> JSONResponse:
    copilot = _get_copilot()
    if copilot is None:
        return JSONResponse(_NOT_CONFIGURED, status_code=503)
    scope = _clamp_scope(req.scope)
    if scope is not None:
        err = scope.validation_error()
        if err:
            return JSONResponse({"error": err}, status_code=400)
    try:
        # A non-empty message is a question (investigate + persist); an empty
        # message is a pure persona switch / re-render of the latest snapshot.
        if req.message.strip():
            return JSONResponse(copilot.ask(cid, req.message, req.persona, scope=scope))
        return JSONResponse(copilot.rerender(cid, req.persona))
    except KeyError:
        return JSONResponse({"error": f"Unknown conversation: {cid!r}"}, status_code=404)


@app.patch("/api/conversations/{cid}")
def rename_conversation(cid: str, req: RenameRequest) -> JSONResponse:
    copilot = _get_copilot()
    if copilot is None:
        return JSONResponse(_NOT_CONFIGURED, status_code=503)
    try:
        copilot.rename(cid, req.title)
        return JSONResponse(copilot.get_conversation(cid))
    except KeyError:
        return JSONResponse({"error": f"Unknown conversation: {cid!r}"}, status_code=404)


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str) -> JSONResponse:
    copilot = _get_copilot()
    if copilot is None:
        return JSONResponse(_NOT_CONFIGURED, status_code=503)
    try:
        copilot.delete(cid)
        return JSONResponse({"ok": True})
    except KeyError:
        return JSONResponse({"error": f"Unknown conversation: {cid!r}"}, status_code=404)


@app.post("/api/conversations/{cid}/artifact")
def artifact(cid: str, req: ArtifactRequest) -> JSONResponse:
    copilot = _get_copilot()
    if copilot is None:
        return JSONResponse(_NOT_CONFIGURED, status_code=503)
    try:
        return JSONResponse(copilot.artifact(cid, req.key))
    except KeyError as exc:
        # Distinguish unknown conversation (404) from unknown artifact key (400).
        if cid in str(exc):
            return JSONResponse({"error": f"Unknown conversation: {cid!r}"}, status_code=404)
        return JSONResponse({"error": f"Unknown artifact: {req.key!r}"}, status_code=400)


def _asset_version(name: str) -> int:
    try:
        return int((_WEB / "static" / name).stat().st_mtime)
    except OSError:
        return 0


@app.get("/")
def index() -> HTMLResponse:
    # The page is static (no templating engine), but we stamp the CSS/JS URLs with
    # their file mtime so a browser can NEVER render new HTML against a stale cached
    # stylesheet/script — the exact breakage that mangles the layout after an edit.
    html = _INDEX.read_text(encoding="utf-8")
    html = html.replace("/static/styles.css", f"/static/styles.css?v={_asset_version('styles.css')}")
    html = html.replace("/static/app.js", f"/static/app.js?v={_asset_version('app.js')}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
