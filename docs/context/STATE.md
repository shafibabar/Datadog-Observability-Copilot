# STATE.md — live status

_Last updated: 2026-07-08_

## Current gate
Plan + Design **approved**. **Iteration 0 COMPLETE**; **Iteration 1 in progress**. **Scope/UI feature approved and in progress** (per-conversation Datadog scope: Environment/Tenant/Duration + persona dropdowns below the composer; real conversation subjects + rename/delete; resizable/collapsible panels; per-response copy). Grounded in **TDD** (see `TESTING.md`).

## Scope/UI feature — progress
- ✅ **Guard** finished + committed (`b0e9316`).
- ✅ **Backend milestone 1** (scope model + scoped Datadog/Replay adapters + reasoning threading + store `scope_json`/delete/rename + API scope-validation/PATCH/DELETE).
- ✅ **Backend milestone 2** (`list_scopes` discovery: Datadog tag-value enumeration with env→tenant narrowing; Replay static set; `/api/scopes`).
- ⏭ **Next: UI milestones 3–5** — control row (Env·Tenant·Duration·Explain-as) below the composer with multiselect+fuzzy search and the 7-day calendar; conversation rename/delete + real subjects in the sidebar; resizable/collapsible panels; per-response copy; remove the `⧉` header icon.

## Tests
**231 / 231 passing (100%).** No pending (red) specs. Prior milestone: **finished the relevance & abuse guard** (`app/guard.py`) that was left red-ahead in the tree — pre-reasoning gate (deterministic Stage 1 blocks empty/over-long/injection + fast-allows on-topic & short in-context follow-ups; hybrid Stage 2 for the ambiguous middle, fails closed; `COPILOT_GUARD_*` settings; wired into `Copilot.ask` before persist/reason; `_SYSTEM` hardened to treat inputs as untrusted). Prior: fixed tab switch (+3); collector test-total (+4); Timeline tab (+10); keyless Claude CLI + Datadog PAT (+11).

## Known gap (deferred)
`.env` is not being loaded at runtime (curl `/api/status` returns defaults: `data_source=replay`, no creds) even on the work laptop with real Datadog creds. Build + tests don't need it (HTTP mocked), but **live** Datadog scope discovery can't be exercised until this is fixed. Fix scheduled before live-validating the scope feature.

## Scope/UI feature — decisions (2026-07-08)
- **Scope model** = `{environments[], tenants[], start, end}`, persisted per conversation, overridable per message, threaded into the DataSource query filter + window.
- **Tenant** is not a native Datadog concept → configurable tag key `DATADOG_TENANT_TAG` (default `tenant`); `env` is the standard environment tag.
- **Duration**: presets + custom, **max 7-day span, end ≤ now**, enforced client- and server-side (token discipline).
- **Conversation subject**: derived from the investigation summary (no extra LLM call).
- **`⧉` header icon removed**; right panel gets a collapse chevron; per-response copy buttons added.
- **Guard Stage-2 classifier** intentionally left unwired (classifier=None → hybrid refuses the ambiguous middle, conservative-safe). Wiring a cheap LLM classifier is a roadmap item.

## Latest session — done (2026-07-03)
- **Fixed: dashboard tabs didn't switch.** They were JS-driven and only tab *presence* was tested, not switching — a broken switch shipped (stale cached JS in the browser). Reworked to a **pure-CSS radio hack** (`:checked ~ #tab-view`): switching now works with no JS; JS only re-renders the visible tab's canvases. +3 tests assert the switch declaratively (two radios, one default-checked; radios-before-views order; the CSS reveal rules). Lesson logged: don't mark UI behavior "manual-smoke-only" — make it declarative + testable.
- **Collector now records passing-test count.** Bug: the collector never set `tests_run/passing/failing`, so every auto-collected impl turn wrote `0` (the dashboard's `113` peak was only from reconstructed history). Fixed with `count_tests(repo)` — a stdlib-only static count of defined `test_…` functions under `tests/` — recorded as `tests_run == tests_passing` (green invariant ⇒ defined == passing). No pytest run in the hook (venv/latency/red-mid-edit reasons). The next auto-collected impl turn records the current total (168 now).
- **Metrics dashboard, two tabs.** Added a second **Timeline** tab: the same metric families rolled up **by calendar day** (from `prompt_ts`) — prompts/tokens/lines/files per day, cumulative tests-passing + cumulative cost over dates, and a per-prompt log table with exact timestamps. Tab 1 (**Overview**) is unchanged. Analytics gained `date`/`prompt_ts` on each row + `by_day` + `timeline_summary` (tolerant: no-timestamp records bucket to `"unknown"`, excluded from the span). Frontend: tabbed HTML/CSS + `renderTimeline()`; `charts.js` untouched. Verified over real HTTP (both tabs + `/api/metrics` timeline keys). See DECISIONS 2026-07-03 (Timeline tab).
- **Ongoing metrics logging confirmed:** the `Stop` hook + `collector.py` keeps appending one record per turn (data now at 27 prompts, `source: live` today).

## Earlier this session — done (2026-07-03)
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
