# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

**Iterations 0–2 are complete** (Iteration 2 pending live Datadog validation on the work laptop). A coherent, runnable four-layer slice exists (telemetry → reasoning → workspace → presentation), plus a separate vibe-coding **metrics** subsystem and a **monitors knowledge base** over the sibling `ec-conduct-dd-monitors` Terraform repo. The suite is green under the binding **once-green-always-green** invariant; for the exact passing count and what's red-ahead (TDD `@pytest.mark.pending`), read `docs/context/STATE.md` — do not trust a hardcoded number here. Read `OBSERVABILITY_COPILOT_KICKOFF.md` (the binding charter) and `docs/context/PROJECT.md` + `docs/context/STATE.md` (the authoritative live status) before doing anything — treat those docs as more current than this section if they disagree.

**Approved stack (kickoff §9 gate cleared):** Python **3.14** (local env is 3.14-only, no Rust toolchain) · FastAPI + Uvicorn · Anthropic SDK · Pydantic · SQLite (stdlib) · dependency-free browser UI (static HTML/CSS/JS, no build step, no Jinja2). Dependencies are pinned to versions with prebuilt 3.14 wheels — see `requirements.txt`. **No new dependency may be added without explicit approval** (kickoff §2).

## Commands

All commands assume the venv is active: `source .venv/bin/activate` (prompt shows `(.venv)`). First-time setup and the full run/demo walkthrough live in `README.md`.

```bash
# Install (app only / app+test)
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run the product app → http://127.0.0.1:8000  (needs ANTHROPIC_API_KEY in .env; degrades gracefully without)
python -m uvicorn app.main:app --port 8000

# Run the metrics dashboard → http://127.0.0.1:8055  (stdlib collector; no key needed)
python -m uvicorn metrics.dashboard:app --port 8055

# Tests (LLM is faked — no API key, no network, no spend)
pytest                                                  # full suite
pytest -q                                               # quiet
pytest tests/test_config.py::test_defaults_when_unset   # a single test
pytest --cov=app                                        # with coverage
```

Tests are marked `@pytest.mark.pending` when written red-ahead-of-implementation (TDD). The regression invariant is binding: **once green, always green** — every step runs the full suite before proceeding. See `docs/context/TESTING.md`.

## Code layout

Four deliberately separable layers (a real backend, more personas/artifacts, and downstream integrations must slot in without rewrites):

- **`app/telemetry/`** — `DataSource` interface (`base.py`) over normalized timestamped events. `ReplayAdapter` (`replay.py`) scripts the canonical deployment-induced latency incident for a reliable demo; `LiveDatadogAdapter` (`datadog.py`) is a read-only Datadog REST adapter. Selected by `COPILOT_DATA_SOURCE` (`replay` default / `datadog`).
- **`app/reasoning/`** — `ReasoningEngine.investigate(question, history=...)` (`engine.py`) calls Claude behind the `LLMClient` seam (`llm.py`, faked in tests) and assembles a structured `Investigation` of reasoning objects (claim · category fact/hypothesis/recommendation/unknown · confidence · evidence pointers), an ordered `timeline.py`, and an `evidence.py` catalog. `domain.py` holds a **static EC domain knowledge base** (services, metric categories, failure modes) baked into `_SYSTEM` at import time. Two real LLM backends implement the seam: `ClaudeCliClient` (shells out to the local `claude` CLI — **no API key**, the "Claude Code way") and `AnthropicClient` (Anthropic SDK, needs a key). `build_copilot` picks one via `COPILOT_LLM_BACKEND` (`auto`/`cli`/`sdk`; `auto` = CLI when no key, else SDK). Conclusions are grounded in evidence; invalid evidence pointers are filtered.
- **`app/workspace/`** — the Investigation Workspace: SQLite **append-with-history** store (`store.py`, versioned snapshots + `messages`/`conversations` tables) and a registry-driven `sections.py` (`serialize_sections()` → JSON for the live panel). This is the architectural center of gravity — a living document, not chat-derived.
- **`app/` presentation & orchestration** — `main.py` (FastAPI: `/api/conversations[/{id}[/chat|/artifact]]`, `/api/status`, `/healthz`), `copilot.py` (`Copilot` conversation-aware service joining the three layers; factory `build_copilot(settings)`), `personas.py` (registry of 5 personas; `render()` re-frames the **same facts** deterministically with **no LLM call**), `artifacts.py` (registry of `ArtifactSpec` transforms over the Investigation, `to_markdown()`; Incident Summary built), `config.py` (secret loading — secrets never touch git or the DB), `web/` (static UI). A pre-reasoning **relevance & abuse guard** (`guard.py`, `evaluate()` → `GuardVerdict`) gates the expensive reasoning path: Stage 1 is deterministic/zero-token (block empty/over-long/injection, fast-allow on a broad keyword list that includes EC service names and queue/processing vocabulary); Stage 2 (hybrid mode) consults an LLM classifier for the ambiguous middle. The Stage-2 classifier **is wired** (`guard_classifier.py` → `classify_relevance`, hooked up in `build_copilot`): note the failure semantics — `guard.py`'s contract fails *closed* if the classifier raises, but `classify_relevance` swallows its own errors and returns True, so the deployed system effectively fails *open* on classifier failure. Wired into `Copilot.ask` before anything is persisted; `_SYSTEM` is hardened to treat inputs as untrusted. Config: `COPILOT_GUARD_ENABLED/MODE/MAX_CHARS`.
- **`app/monitors/`** — knowledge base of Datadog monitors/dashboards parsed from the **sibling Terraform repo** `ec-conduct-dd-monitors`. `index.py` scans that repo's `modules/*/main.tf` for `datadog_monitor` resources and builds a `MonitorsIndex` (monitors + dashboards); `get_monitors_context()` formats it for prompt injection, which `engine.py` includes when the question matches monitor keywords. **Caveat:** the repo path is a hardcoded absolute path (`/Users/shafibabar/SmarshGitRepos/ec-conduct-dd-monitors`) — on any other machine it degrades to an empty index (no crash, but no monitor knowledge). Making it configurable (e.g. `MONITORS_REPO_PATH`) is an open item.
- **`metrics/`** — separate vibe-coding metrics subsystem (not part of the product). `collector.py` (stdlib-only) is run by the **`Stop` hook** in `.claude/settings.json` and appends one record per prompt cycle to `prompts.jsonl`; `analytics.py` is a tolerant loader/aggregator; `dashboard.py` + `static/` serve a dependency-free canvas dashboard.

The **persona system, Workspace sections, and artifact types are registry/config-driven, not hard-coded** (kickoff §8) — they are designed to grow. Keep that seam intact when extending.

## Operating model (non-negotiable — kickoff §2)

The human partner **does not write, edit, or debug code, ever**. Internalize this; it shapes every workflow:

- **Claude owns 100% of technical execution** — code, config, tests, scripts, schemas, mock-data generators, and the run instructions.
- **The human owns approvals and physical actions only**, and only when given exact, copy-pasteable commands: approving plans/designs/dependencies, creating the repo, running commits, running things locally and pasting output back, and account/key setup.
- **Work proceeds through approval gates:** Plan → Design → Roadmap → (human approval) → Implementation, iteration by iteration. Nothing significant proceeds without an explicit "approved."
- **Plan before code, always.** When the charter and a coding instinct conflict (e.g. "just scaffold it and show the user"), the charter wins — ask first.
- **Propose, don't silently decide** anything that adds a dependency, changes architecture, or affects cost/security. Give recommendation + alternatives + trade-off + a default, then wait. No paid service or external dependency may be added without explicit approval.
- **One clear action at a time** when the human must act: numbered, with literal commands and where to type them. Never assume developer conventions (PATH, venv, etc.) are known.
- Label assumptions explicitly so they can be corrected. End each session by stating what got done, what's next, and what's needed to proceed.

## Project memory (non-negotiable — kickoff §2)

The project spans multiple sessions and may resume on a different machine or a different Claude account. **All durable context must live in structured, version-controlled files committed to the repo — never only in chat.** Chat is disposable; the files are the single source of truth. The planned context files (propose exact layout for approval, e.g. under `/docs/context/`):

- `PROJECT.md` — read-me-first orientation: vision, operating-model summary, constraints, approved stack, how to resume.
- `STATE.md` — live snapshot: done / in-progress / next / current approval gate. Update every session.
- `DECISIONS.md` — decision log (lightweight ADRs): date, choice, alternatives, reason. Stops re-litigating settled questions.
- `ROADMAP.md` — iterations, what's in each, what's deferred.
- `BUILD-LOG.md` — running narrative of how the solution came together (feeds the presentation's meta-story, §7.2).
- `GLOSSARY.md` — key terms, workspace data model, persona/artifact registries.
- `OPEN-QUESTIONS.md` — unresolved items awaiting human input.

**Protocol:** start each session by reading at least `PROJECT.md` and `STATE.md` and treating them as authoritative over your own recollection; write decisions/assumptions/state changes to the right file as they happen; at session end and each milestone, update the files and provide exact commit commands. Keep these files concise (summaries and pointers, not transcripts) for token/cost discipline. The portability test: repo + kickoff prompt alone should let a fresh session on any account resume correctly.

## What is being built

An **AI-powered Observability Copilot** — a reasoning layer on top of observability telemetry that turns dashboards into guided, evidence-backed investigations. It is explicitly *not* a chatbot and *not* a dashboard replacement; the dashboard stays the primary source of truth and the Copilot interprets over it. The product lifecycle to embody: **Observe → Understand → Investigate → Explain → Recommend → Execute → Document → Learn.**

Core philosophy that constrains every feature: explain metrics rather than expose them; tell the story rather than show graphs; every conclusion carries supporting evidence; and the AI must always distinguish **Facts vs. Hypotheses vs. Recommendations vs. Unknowns**, with confidence derived from and traceable to evidence — never speculation presented as certainty.

## Architecture (the seams to preserve — kickoff §5, §8)

We build a **coherent working slice, architected for extension**, not the whole product. Establish clean, replaceable seams across four layers:

- **Telemetry / data layer** — synthetic/mock telemetry for now, behind an interface so a real metrics/logs/traces backend can replace it without rewrites. Must support **replaying a known incident** (canonical: a deployment-induced latency incident) so the live demo is reliable, while the AI reasoning over it stays genuine (never hard-coded answers). All event sources (deploys, metric threshold crossings, log spikes, trace anomalies, support signals) normalize into a **common timestamped event model** that merges into one ordered timeline.
- **Reasoning / AI layer** — produces structured reasoning objects, each carrying: the claim, its category (fact/hypothesis/recommendation/unknown), a confidence level, and pointers to supporting/contradicting evidence. Root-cause hypotheses are first-class objects with for/against evidence and required "contradictory evidence" and "missing information" fields; confidence must be revisable and hypotheses retirable as evidence changes.
- **Investigation-state layer — the Investigation Workspace (architectural center of gravity, kickoff §5.9).** A real persisted, versioned investigation-state model — a *living document*, not derived from chat. Each new observation reinforces, contradicts, or refines prior conclusions; historical reasoning stays visible (append-with-history, confidence over time, contradiction tracking). Personas render *from* it, the conversation reads/writes *to* it, artifacts serialize *from* it.
- **Presentation layer** — dashboard + copilot UI coexisting (dashboard alongside an investigation panel, not full-screen chat). Progressive disclosure: headline → summary → evidence → raw telemetry, with "show me the evidence" a first-class, always-available action.

**Extensibility requirement:** the **persona system**, the **Workspace sections**, and the **output-artifact types** must all be registry/config-driven, not hard-coded — they will grow. A persona is a config (which concerns to surface, vocabulary level, detail depth) that changes only the rendering lens, never the underlying facts. Each artifact (Incident Summary, Executive Briefing, Technical Investigation Report, Customer Communication Draft, Post-Incident Report, Runbook Recommendation) is a transform over the same Workspace state; runbook recommendations are gated on a confidence threshold and must always cite evidence. Downstream integrations (incident management, ticketing, comms) are **stubbed adapters behind clean interfaces** for now.

## Demo has two objectives (kickoff §7)

- **Product story (A):** the live narrative — complex dashboard → activate Copilot → health summary → significant changes → operational timeline → likely cause → evidence → persona-adapted explanations → at least one generated artifact, all backed by the living Workspace.
- **Meta story (B), which matters most:** demonstrating that *a non-developer directed AI to design and build a working AI-powered solution rapidly*. The **process is the message** — treat the build journey as a first-class deliverable (this is why `BUILD-LOG.md` and `DECISIONS.md` exist). Optimize for a quick, credible, easy-to-run, easy-to-explain solution over heavyweight engineering. When a choice makes the product marginally fancier but the story slower or harder to explain, prefer the simpler, faster, more explainable path.
