"""FastAPI entry point for the Observability Copilot.

Iteration 0 foundation: boots the app, serves the chat UI, and exposes a
secret-free status endpoint. The /api/chat route is a placeholder until the
reasoning engine and data source are wired in the next build step.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings

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


@app.post("/api/chat")
def chat(req: ChatRequest) -> JSONResponse:
    # Placeholder. The Claude-powered reasoning engine is wired in the next step.
    return JSONResponse(
        {
            "reply": (
                "The reasoning engine isn't connected yet — this is the foundation "
                "skeleton. Once wired, I'll investigate over your telemetry and answer "
                "as evidence-backed Facts / Hypotheses / Recommendations / Unknowns."
            ),
            "persona": req.persona,
        }
    )


@app.get("/")
def index() -> FileResponse:
    # The page is fully static (no server-side templating), so serve it directly.
    return FileResponse(_INDEX)
