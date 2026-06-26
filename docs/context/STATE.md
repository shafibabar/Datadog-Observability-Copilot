# STATE.md — live status

_Last updated: 2026-06-26_

## Current gate
Plan + Design **approved**. In **Implementation — Iteration 0**. Grounded in **TDD** (see `TESTING.md`).

## Tests
**43 / 43 passing (100%).** No pending (red) specs. Latest: Claude reasoning engine (test-first, Claude fully mocked).

## Done
- Plan + Design approved (stack, dependencies, roadmap shape, context-file layout, key-handling constraint).
- `CLAUDE.md` written (guidance for future Claude sessions).
- Iteration 0 **foundation scaffold**:
  - `.gitignore` (secrets/`.env`/db excluded), `.env.example` (empty template), `requirements.txt`.
  - `app/config.py` — secure runtime secret loading (single seam; secret-free `status()`).
  - `app/main.py` — FastAPI app: `/healthz`, `/api/status`, `/` chat page, `/api/chat` (placeholder).
  - Chat UI: `app/web/templates/index.html`, `static/styles.css`, `static/app.js` (persona selector, status banner).
  - `docs/context/` files created.
- **TDD setup + foundation test baseline**: `pytest.ini`, `requirements-dev.txt`, `tests/test_config.py`, `tests/test_app.py`. 11/11 green. Verified by Claude in a clean venv.

## In progress
- Awaiting human to run the foundation + tests locally and confirm (see commit/run commands in chat).

## Next (Iteration 0 remainder) — all test-first from here
1. ~~`DataSource` interface + ReplayAdapter (canonical incident)~~ ✅ done.
2. ~~LiveDatadogAdapter (read-only)~~ ✅ done (HTTP mocked in tests).
3. ~~Claude reasoning engine~~ ✅ done (structured objects, timeline, evidence grounding; Claude mocked in tests).
4. **Investigation Workspace** (SQLite, append-with-history) + core sections.
5. Wire `/api/chat` to the workspace + reasoning; persona-rendered answers; "show me the evidence".
6. One artifact: **Incident Summary**.
7. Run instructions in README.

## Needed from human
- Run the foundation locally and paste any errors.
- Keys NOT needed yet (only when reasoning/live-Datadog steps land).
