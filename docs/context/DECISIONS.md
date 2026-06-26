# DECISIONS.md — decision log (lightweight ADRs)

Newest first. Each: date · decision · alternatives · why.

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
