# STATE.md — live status

_Last updated: 2026-07-03_

## Current gate
Plan + Design **approved**. **Iteration 0 COMPLETE**; **Iteration 1 in progress** — multi-conversation + conversational memory + new 3-pane UI shipped (approved scope). Grounded in **TDD** (see `TESTING.md`).

## Tests
**154 / 154 passing (100%), 99% cov.** No pending (red) specs. Latest: **keyless Claude via the `claude` CLI** (`ClaudeCliClient` behind the `LLMClient` seam) + **Datadog Personal Access Token** (Bearer) support — both test-first, +11 specs. Prior: vibe-coding metrics subsystem (`metrics/`).

## Latest session — done (2026-07-03)
- **No API key needed.** `ClaudeCliClient` (`app/reasoning/llm.py`) shells out to the local `claude` CLI headless (`claude -p …`), reusing the Claude Code login. `COPILOT_LLM_BACKEND` (`auto`/`cli`/`sdk`) selects the backend; `auto` = CLI when keyless, else SDK. `build_copilot(settings, cli_available=…)` reworked; returns None only when there's no key **and** no CLI. Subprocess runner + CLI detection injected → suite stays offline.
- **Datadog PAT.** `DATADOG_ACCESS_TOKEN` → `Authorization: Bearer`; preferred over the legacy `DD-API-KEY`/`DD-APPLICATION-KEY` pair (kept as fallback). `has_datadog` true with a token alone.
- **Docs.** README rewritten (Connect-Claude section w/ obtain steps for CLI + API key; Datadog PAT obtain steps; **metrics dashboard run section**). `.env.example`, `CLAUDE.md`, `DECISIONS.md` updated. See DECISIONS 2026-07-03.

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
- **Metrics subsystem shipped** (separate from the product, in `metrics/`). Run the dashboard: `python -m uvicorn metrics.dashboard:app --port 8055` → http://127.0.0.1:8055. The `Stop` hook in `.claude/settings.json` auto-appends a record after each prompt (loaded — confirmed firing).
- Deferred app work (pre-metrics): persist per-message evidence for reload; the Claude **CLI LLM backend** (`ClaudeCliClient` behind the `LLMClient` seam — planned/approved, not built); more artifacts.

## Metrics subsystem — done this session (2026-06-27)
- `metrics/prompts.jsonl` (JSONL data) + `SCHEMA.md`; historical baseline reconstructed from transcripts (real tokens/timestamps) + git + TESTING.md.
- `metrics/collector.py` (stdlib-only) run by a `Stop` hook → appends one record per prompt cycle; per-turn git delta arithmetic; dedupe.
- `metrics/analytics.py` tolerant loader + aggregations (robust to schema evolution / malformed lines).
- `metrics/dashboard.py` (FastAPI) + `metrics/static/` (dependency-free canvas charts) → live local dashboard on a free port.

## Iteration 1 — done this session
- **Conversational memory:** `ReasoningEngine.investigate(question, history=...)` feeds bounded recent turns into the prompt (`history_limit`, default 6). Follow-ups now carry context.
- **Multiple conversations:** a conversation = one Workspace + its messages, all persisted. Store gained a `messages` table, `title`/`updated_at` on workspaces, and `add_message`/`get_messages`/`list_conversations`/`set_title`. Activity bumps recency.
- **Conversation-aware service:** `CopilotSession` → **`Copilot`** (`app/copilot.py`): `new_conversation`, `list_conversations`, `get_conversation`, `ask` (persists turns + memory), `rerender` (no LLM), `artifact`. Factory renamed `build_default_session` → **`build_copilot`**.
- **Section serializer:** `serialize_sections()` (type-dispatched) → JSON for the live panel.
- **API:** `/api/conversations` (GET list, POST create), `/api/conversations/{id}` (GET), `/{id}/chat`, `/{id}/artifact`. 404 on unknown conversation, 400 on unknown artifact, 503 keyless.
- **New 3-pane UI:** conversation sidebar (list/new/switch, last-opened persisted in localStorage) · restyled chat with markdown + per-reply evidence disclosure · collapsible **live Investigation Workspace panel** rendering serialized sections with confidence/severity color vocabulary. Boot + shape smoke-tested.

## Next (Iteration 0 remainder) — all test-first from here
1. ~~`DataSource` interface + ReplayAdapter (canonical incident)~~ ✅ done.
2. ~~LiveDatadogAdapter (read-only)~~ ✅ done (HTTP mocked in tests).
3. ~~Claude reasoning engine~~ ✅ done (structured objects, timeline, evidence grounding; Claude mocked in tests).
4. ~~Investigation Workspace (SQLite, append-with-history) + core sections~~ ✅ done (`app/workspace/`: store + registry-driven sections; confidence-over-time; 14 specs).
5. ~~Wire `/api/chat` to workspace + reasoning; persona-rendered answers; "show me the evidence"~~ ✅ done (`app/copilot.py` CopilotSession; `app/personas.py` registry+render; evidence ships per reply; UI persona-switch re-renders without re-reasoning; 14 specs).
6. ~~One artifact: Incident Summary~~ ✅ done (`app/artifacts.py`: registry-driven transform; `/api/artifact`; UI button; 11 specs).
7. ~~Run instructions in README~~ ✅ done (full non-dev copy-paste guide + demo walkthrough; boot verified via smoke test).

**→ Iteration 0 definition of done MET.** Next gate: agree Iteration 1 scope (candidates in ROADMAP "Later iterations").

## Needed from human
- Tests run keyless (LLM faked). To run the app **live** locally you now need **either** a Claude Code CLI sign-in (`claude`, no key — default) **or** an `ANTHROPIC_API_KEY` in `.env`; chat degrades gracefully with neither. Datadog only if `COPILOT_DATA_SOURCE=datadog` — a `DATADOG_ACCESS_TOKEN` (PAT) or the legacy API+App key pair.
