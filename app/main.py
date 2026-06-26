"""FastAPI entry point for the Observability Copilot.

Boots the app, serves the chat UI, exposes a secret-free status endpoint, and
wires /api/chat to a CopilotSession (DataSource + ReasoningEngine + Workspace +
persona rendering). The session is built lazily from runtime settings; when no
Anthropic key is configured the chat route degrades gracefully instead of
crashing, so the app still runs for a non-developer before keys are placed.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings
from app.copilot import CopilotSession, build_default_session

_WEB = Path(__file__).resolve().parent / "web"
_INDEX = _WEB / "templates" / "index.html"

app = FastAPI(title="Observability Copilot", version="0.1.0")
app.mount("/static", StaticFiles(directory=_WEB / "static"), name="static")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> JSONResponse:
    """Secret-free runtime status — drives the UI banner."""
    return JSONResponse(settings.status())


class ChatRequest(BaseModel):
    message: str
    persona: str = "sre"


def _get_session() -> CopilotSession | None:
    """Return the active session, building one lazily from settings. Tests may
    pre-set `app.state.session` to inject an offline (fake-LLM) session."""
    session = getattr(app.state, "session", None)
    if session is not None:
        return session
    session = build_default_session(settings)
    if session is not None:
        app.state.session = session
    return session


@app.post("/api/chat")
def chat(req: ChatRequest) -> JSONResponse:
    session = _get_session()
    if session is None:
        return JSONResponse(
            {
                "reply": (
                    "Claude isn't configured yet. Add ANTHROPIC_API_KEY to a local "
                    ".env file and restart to enable evidence-backed investigations."
                ),
                "persona": req.persona,
                "configured": False,
            }
        )
    # A non-empty message is a question (investigate + append a snapshot); an
    # empty message is a pure persona switch / "show me the evidence" re-render.
    if req.message.strip():
        result = session.ask(req.message, req.persona)
    else:
        result = session.rerender(req.persona)
    return JSONResponse(result)


@app.get("/")
def index() -> FileResponse:
    # The page is fully static (no server-side templating), so serve it directly.
    return FileResponse(_INDEX)
