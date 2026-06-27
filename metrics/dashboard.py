"""Local metrics dashboard — FastAPI serving the analytics + a static page.

Reuses the project's existing stack (FastAPI/uvicorn): no new Python dependency,
runs offline. Live graphs (step 5) poll `/api/metrics`, which returns the pure
aggregation over `metrics/prompts.jsonl`. `create_app(data_path)` keeps the data
source injectable so tests point at a temp file.

Run:  python -m uvicorn metrics.dashboard:app --port 8055
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from metrics.analytics import load_and_aggregate

_HERE = Path(__file__).resolve().parent
DEFAULT_DATA_PATH = str(_HERE / "prompts.jsonl")


def create_app(data_path: str = DEFAULT_DATA_PATH) -> FastAPI:
    app = FastAPI(title="Vibe Coding Metrics")
    static_dir = _HERE / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/api/metrics")
    def metrics() -> JSONResponse:
        # Recomputed each request → "live": the page polls this endpoint.
        return JSONResponse(load_and_aggregate(data_path))

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def index():
        page = static_dir / "dashboard.html"
        if page.exists():
            return FileResponse(page)
        return HTMLResponse("<h1>Vibe Coding Metrics</h1>")

    return app


app = create_app()
