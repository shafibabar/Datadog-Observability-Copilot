# PROJECT.md — read me first

Orientation for any fresh session (any machine, any account). Read this and `STATE.md` before doing anything. The kickoff charter is `OBSERVABILITY_COPILOT_KICKOFF.md` at the repo root; this file summarizes it.

## Vision (brief)
An AI-powered **Observability Copilot**: a backend-hero reasoning layer that turns observability telemetry into guided, evidence-backed investigations. Not a chatbot, not a dashboard replacement. It explains system health, reconstructs incident timelines, reasons about root causes (Facts / Hypotheses / Recommendations / Unknowns, each with confidence + evidence), and adapts explanations per persona. Lifecycle: Observe → Understand → Investigate → Explain → Recommend → Execute → Document → Learn.

## Operating model (binding)
- The human partner **never writes, edits, or debugs code.** Claude owns 100% of technical execution.
- The human only: approves, creates the repo, runs commit/run commands given verbatim, pastes output back, sets up keys.
- Approval gates: **Plan → Design → Roadmap → (approval) → Implementation, iteration by iteration.** Plan before code, always.
- Propose (recommendation + alternatives + default), don't silently decide, for anything adding a dependency / changing architecture / affecting cost or security. No paid service without explicit approval.
- All durable context lives in `docs/context/` files, committed — never only in chat. Files are authoritative over recollection.

## Approved tech stack
- **Backend:** Python + FastAPI. **Reasoning:** two `LLMClient` backends behind one seam — the **Claude Code CLI** (`claude -p`, no API key, the default when keyless) and the **Anthropic SDK** (needs a key); no LangChain. **UI:** single static browser page served by FastAPI (HTML/CSS/JS, `fetch`/JSON — no SSE, no build step, no framework), Claude.ai-style, thin client over a strong backend; CSS/JS URLs are mtime-versioned to defeat stale caches. **Workspace state:** SQLite (append-only history).
- Deps (free, permissive): fastapi, uvicorn, anthropic, httpx, pydantic, python-dotenv. (Jinja2 dropped — the page is static; see DECISIONS.) Optional dev-only extra: playwright (browser smoke test, not in requirements).
- **Models (cost-conscious):** Haiku for routine extraction passes, Sonnet for deep reasoning/narrative. Never silently use a pricier model.

## What's built (high level)
Four separable layers — **telemetry** (DataSource: ReplayAdapter + read-only LiveDatadogAdapter), **reasoning** (structured Fact/Hypothesis/Recommendation/Unknown + timeline + evidence grounding), **Workspace** (SQLite append-with-history), **presentation** (conversation sidebar · chat · live Workspace panel). Plus: multi-conversation memory; a registry of 5 personas and the Incident Summary artifact; a pre-reasoning **relevance & abuse guard**; and **scoped investigations** — a per-conversation `Scope` (environments/tenants/time window, ≤7 days) chosen from a drill-down scope menu under the prompt and threaded into the data queries. A separate `metrics/` subsystem audits the build. See `STATE.md` for the live status and `ROADMAP.md` for what's next.

## Hard constraints
- **Secrets never committed.** Keys (Anthropic, Datadog) load at runtime from a gitignored `.env` (or real env vars), never written to disk or the DB, never logged. `.env.example` is the only committed template. Later: swap to Vault/Okta via the single `app/config.py` seam.
- Runs **locally**, ideally one or two commands. Must be runnable by a non-developer from copy-paste instructions.
- Data source is pluggable behind one interface: **live read-only Datadog adapter** + **replay adapter** (scripted known incident for reliable demos).

## How to resume this project
1. Read `PROJECT.md` (this file) + `STATE.md`.
2. Skim `DECISIONS.md` (don't re-litigate) and `ROADMAP.md` (what's next).
3. Continue from the current gate noted in `STATE.md`. Update the context files as you work; provide exact commit commands at session end.

## How to run (local)
Full copy-paste instructions for a non-developer live in **`README.md`** (the authoritative run guide). In short:
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # then edit .env, add ANTHROPIC_API_KEY
python -m uvicorn app.main:app --port 8000
```
Then open http://127.0.0.1:8000 . The app starts without a key (chat reports it isn't configured); add `ANTHROPIC_API_KEY` to enable real reasoning, and optionally Datadog keys for the live source. Verified booting via smoke test (2026-06-26).
