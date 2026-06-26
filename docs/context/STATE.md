# STATE.md — live status

_Last updated: 2026-06-26_

## Current gate
Plan + Design **approved**. In **Implementation — Iteration 0**. Grounded in **TDD** (see `TESTING.md`).

## Tests
**82 / 82 passing (100%).** No pending (red) specs. Latest: Incident Summary artifact (registry-driven transform over workspace state; LLM faked).

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
- Next: **README run instructions** (exact copy-paste for a non-dev) → completes Iteration 0 DoD.

## Next (Iteration 0 remainder) — all test-first from here
1. ~~`DataSource` interface + ReplayAdapter (canonical incident)~~ ✅ done.
2. ~~LiveDatadogAdapter (read-only)~~ ✅ done (HTTP mocked in tests).
3. ~~Claude reasoning engine~~ ✅ done (structured objects, timeline, evidence grounding; Claude mocked in tests).
4. ~~Investigation Workspace (SQLite, append-with-history) + core sections~~ ✅ done (`app/workspace/`: store + registry-driven sections; confidence-over-time; 14 specs).
5. ~~Wire `/api/chat` to workspace + reasoning; persona-rendered answers; "show me the evidence"~~ ✅ done (`app/copilot.py` CopilotSession; `app/personas.py` registry+render; evidence ships per reply; UI persona-switch re-renders without re-reasoning; 14 specs).
6. ~~One artifact: Incident Summary~~ ✅ done (`app/artifacts.py`: registry-driven transform; `/api/artifact`; UI button; 11 specs).
7. **Run instructions in README** — last item for Iteration 0 DoD.

## Needed from human
- Tests run keyless (LLM faked). To run the app **live** locally, an `ANTHROPIC_API_KEY` in `.env` is now required (chat degrades gracefully without it). Datadog keys only if `COPILOT_DATA_SOURCE=datadog`.
