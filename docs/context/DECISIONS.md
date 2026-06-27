# DECISIONS.md — decision log (lightweight ADRs)

Newest first. Each: date · decision · alternatives · why.

## 2026-06-27 · Vibe-coding metrics subsystem: JSONL + Stop-hook collector + FastAPI/canvas dashboard
**Decision:** A separate `metrics/` subsystem (outside the product `app/`) audits the AI-assisted build. Three layers: **data** = append-only `prompts.jsonl` (one record per prompt cycle); **collection** = `collector.py` run by a Claude Code `Stop` hook (`.claude/settings.json`), parsing the session transcript for *real* tokens/timestamps and git for per-turn line/file deltas; **analytics/dashboard** = `analytics.py` (tolerant loader + pure aggregations) served by `dashboard.py` (FastAPI) with a **dependency-free canvas charting module** (`static/charts.js`). Historical entries reconstructed from transcripts + git + `TESTING.md`, flagged `estimated` where attribution is approximate.
**Alternatives / forced change:** the approved plan was FastAPI **+ vendored Chart.js**, but the environment has **no network** (couldn't download Chart.js, even outside the sandbox), and a runtime CDN `<script>` would break offline use — so I wrote a small zero-dependency canvas renderer instead. SQLite/CSV data store (rejected — JSONL is append-only, diff-friendly, human-readable, charter-aligned); Streamlit/Plotly dashboard (rejected — heavy deps, Python-3.14 wheel risk).
**Why:** Serves the charter's meta-story (§7.2, the build process as a first-class deliverable). Stdlib-only collector + existing-stack dashboard = zero new dependencies, no paid service, fully offline. Tolerant loader guarantees new / future-schema data can never break the dashboard. **Caveats:** tool-confirmation (Y/N) prompts and exact red/green test runs aren't fully auto-captured; cost is an estimate (records don't store the per-call model).

## 2026-06-26 · Iteration 1: a conversation = a Workspace + messages; recent-turn memory; 3-pane UI
**Decision:** Support multiple conversations and conversational memory. A conversation IS a Workspace plus a persisted `messages` history (no separate "conversation" entity) — the store was already per-workspace, so this is additive. `CopilotSession` became a conversation-aware **`Copilot`** service whose methods take a `conversation_id`; the process no longer holds one global session. Conversational memory = the last N turns (default 6, `history_limit`) fed into the reasoning prompt; **persona switches and artifacts are NOT persisted as messages** (history stays = real Q&A). New UI is a **3-pane layout** (conversation sidebar · chat · live Investigation Workspace panel) chosen over the eventual full dashboard-with-charts (deferred). Approved by the human via AskUserQuestion (memory: full recent-turn; UI: sidebar + polish + live Workspace panel).
**Alternatives:** a separate conversations table 1:1 with workspaces (rejected — redundant; workspace already fits); full transcript to the model every turn (rejected — unbounded token cost; bounded window instead); summary memory (offered, not chosen); per-session in-memory threads (rejected — wouldn't survive restart, charter wants persisted state); full dashboard+charts now (deferred — larger build, slower demo story).
**Why:** Directly serves §5.7 (full conversational context) and §5.9 (living document visible beside the chat) while keeping token cost bounded (human's "spend on product, save during demo"). Persisting only real dialogue keeps memory meaningful and cheap. **Trade-off noted:** per-message evidence isn't persisted, so reloaded past bubbles lack the evidence disclosure — the always-current Workspace panel covers evidence; revisit if needed.

## 2026-06-26 · Domain ordering lives on the enums; shared `outstanding_questions` helper
**Decision:** `Confidence` and `Severity` expose a `.rank` property (LOW<MEDIUM<HIGH, INFO<WARNING<CRITICAL); callers sort/compare via it. Removed the private rank-maps that `artifacts.py` had duplicated. Extracted `outstanding_questions(inv)` into `app/workspace/sections.py` and reused it from both the Workspace section and the Incident Summary artifact so the two can't drift. Section/artifact code now compares `EventSource.SUPPORT` (enum) rather than the `"support"` string.
**Alternatives:** keep per-module rank maps (rejected — duplication that would multiply as more artifacts/personas sort by confidence); duplicate the questions logic (rejected — already drifting risk); leave string compares (rejected — not type-safe).
**Why:** Ordering is intrinsic to the domain model, so it belongs there; one definition prevents drift. Behavior-preserving refactor guarded by the existing suite, then hardened with +16 specs (now 98 tests, 99% coverage) including a security guard that no secret bytes ever land in the workspace DB.

## 2026-06-26 · Chat loop: ask appends a snapshot; persona-switch re-renders with no LLM call; rendering is deterministic
**Decision:** `CopilotSession` (`app/copilot.py`) drives the chat. A non-empty message = a question → `engine.investigate()` + **append** a Workspace snapshot, then render. An empty message = a pure persona switch / "show me the evidence" → **re-render the latest snapshot with NO new LLM call**. Persona rendering (`app/personas.py`) is deterministic composition over the structured `Investigation` via the section registry (not a second LLM pass). Every reply ships its full evidence catalog so "show me the evidence" needs no special endpoint. Session built lazily from settings; absent an Anthropic key the chat degrades gracefully (returns a "not configured" message).
**Alternatives:** re-run reasoning on every persona switch (rejected — costs tokens and risks changing the "facts" when only the lens should change, violating §5.1); a second LLM "render" pass per persona (deferred — nice prose but slower/costlier/harder to test; deterministic composition is grounded and free); a dedicated `/api/evidence` endpoint (rejected — shipping evidence inline makes it always-available per §5.8/§6.7); construct the session at import (rejected — would crash keyless and break the offline test suite).
**Why:** Directly encodes the charter's "facts don't change, only the lens" and "evidence always available," keeps spend to one investigation per genuine question (cost-conscious mode), and keeps the whole suite runnable offline with the LLM faked.

## 2026-06-26 · Investigation Workspace = SQLite append-with-history over the `Investigation` object
**Decision:** Persist the living investigation as immutable, sequentially-numbered snapshots (one per `record()`), each holding the full reasoning `Investigation` JSON. Reasoning objects are flattened into a queryable `reasoning_objects` table; each hypothesis's confidence is logged per snapshot into `confidence_history`, keyed by a whitespace/case-normalised hash of its statement text (gives stable identity across passes even though the LLM emits fresh objects each time). Workspace sections are a **Python registry** (`app/workspace/sections.py`) of pure `Investigation -> content` transforms. Confidence uses the existing `Confidence` enum (low/medium/high) — **not** a 0–1 float (corrected a drift in the initial proposal).
**Alternatives:** derive state from chat history (rejected — charter forbids; must be real persisted state); mutate a single current-state row (rejected — destroys history); JSON-table sections (rejected — Python config is more legible/versionable for a non-dev story); float confidence (rejected — second representation, inconsistent with reasoning layer).
**Why:** Charter §5.9 names the Workspace the architectural center of gravity and demands a real, versioned, append-with-history model where prior reasoning stays visible. Building on the engine's existing `Investigation` keeps the seam clean: personas render from it, artifacts serialize from it.

## 2026-06-26 · TDD is the grounding discipline
**Decision:** All implementation is grounded in TDD (pytest). Regression invariant: green tests stay green. New capabilities are written test-first; pending specs marked `@pytest.mark.pending`. Each step reports `passing/total (%)`; any pass-% dip caused by newly added red spec tests is stated explicitly. Log in `docs/context/TESTING.md`.
**Why:** Human directive. Also strengthens the meta-story — green tests are objective proof the AI-built solution works.

## 2026-06-26 · Pin dependency versions to Python-3.14 wheels; drop Jinja2
**Decision:** Only Python 3.14 is available locally with no Rust/compiler, so pinned versions that ship prebuilt cp314 wheels (pydantic 2.13.4, fastapi 0.138.1, uvicorn 0.49.0, anthropic 0.112.0, etc.). Dropped `uvicorn[standard]` extras and Jinja2 (the index page is fully static → served via FileResponse, avoiding a Jinja2/3.14 cache bug).
**Alternatives:** install Rust to compile pydantic-core (rejected — slower, fragile, worse for a non-dev's one-command run); older Python (not available).
**Why:** Keep install to wheels-only so a non-developer runs `pip install` with no toolchain.

## 2026-06-26 · Secrets via gitignored .env, never committed
**Decision:** API keys (Anthropic, Datadog) load at runtime from a local gitignored `.env` (or real env vars) through `app/config.py`. Never hardcoded, committed, logged, or written to the workspace DB. `.env.example` (empty) is the only committed template.
**Alternatives:** hardcoded keys (rejected — would leak to GitHub); secret manager now (deferred — overkill for demo).
**Why:** Human requirement: nothing secret committed; pick up keys from an external file during the demo only. Vault/Okta later is a one-file change at the `config.py` seam.

## 2026-06-26 · Tech stack: Python + FastAPI, Anthropic SDK, chat UI, SQLite
**Decision:** Python/FastAPI backend; Anthropic SDK directly for reasoning; a single lightweight FastAPI-served chat page (HTML/JS) as a thin client; SQLite for the append-history Investigation Workspace.
**Alternatives:** Node/TS; React/Next.js UI (adds Node toolchain); LangChain (opaque, heavy); JSON-file state.
**Why:** Backend is the hero and UI is thin; optimize for one-command local run by a non-developer and a legible "non-dev directs AI" build story. SQLite is zero-install and supports versioned history.

## 2026-06-26 · Models: Haiku (fast) + Sonnet (deep), cost-conscious
**Decision:** Default to a cheaper model (Haiku) for routine extraction/classification and a stronger model (Sonnet) for deep reasoning/narrative. Configurable via env. Never silently escalate to a pricier model.
**Why:** Human chose cost-conscious mode. Keep token use tight; flag anything that could grow cost.

## 2026-06-26 · Data source: one interface, two adapters (live Datadog + replay)
**Decision:** A single `DataSource` interface with a live read-only Datadog adapter and a replay/synthetic adapter (scripted known incident). App selects per session.
**Alternatives:** live-only (unreliable demo); replay-only (never touches real data).
**Why:** Satisfies both the charter's repeatable-demo requirement and the human's goal of using real production Datadog.
