# BUILD-LOG.md — the journey (feeds the presentation meta-story)

Running narrative of how the solution came together: what was fast, what was hard, where AI accelerated, where human judgment was required.

## 2026-06-26 — Kickoff, planning, and foundation
- **Human judgment / direction:** The human (non-developer) supplied the charter and made the high-leverage calls — local run that can still connect to *real* production Datadog; chat-style UI with the **backend as the hero**; cost-conscious LLM use; and the firm constraint that **secrets are never committed** (loaded from an external file during the demo, Vault/Okta later).
- **AI accelerated:** Turned the charter into clarifying questions, a tech-stack recommendation with trade-offs, a phased roadmap, and the full project-memory structure — then scaffolded the foundation (secure config, FastAPI app, chat UI, context files) in one pass.
- **Key insight surfaced:** live Datadog vs. a reliable scripted demo are in tension → resolved cleanly with one `DataSource` interface and two adapters (live + replay). The architecture the charter asked for (clean seams) made this a non-issue.
- **Fast:** dependency choice, secret-handling design, and the chat UI skeleton.

## 2026-06-26 — TDD adopted as the grounding discipline
- **Human judgment / direction:** Human directed that the whole build be grounded in TDD, with pass-% always trending up, no regressions, and any dip from newly added spec tests stated explicitly.
- **AI did:** set up pytest, wrote the foundation test suite, and **caught two real environment problems by actually running the tests** (not just writing them): (1) Python 3.14-only with no Rust → `pydantic 2.10.4` failed to compile; fixed by pinning wheels-available versions. (2) A Jinja2/3.14 template-cache bug → removed Jinja2 since the page is static. Suite went green at **11/11**.
- **Meta-story value:** This is the TDD payoff made visible — the AI's own tests surfaced bugs before the human ever ran anything, and the green suite is objective proof the foundation works.
- **Next:** the reasoning engine and the living Investigation Workspace — genuinely test-first from here.

## 2026-06-26 — Investigation Workspace (the architectural center of gravity)
- **Human judgment / direction:** Human chose to build the Workspace next (not run the foundation first) and approved the design in one pass — snapshot on every record, a confidence-history table, and Python-config (not table) sections.
- **AI did:** Before writing the schema, re-read the existing reasoning/telemetry models and **caught a design drift** — my initial proposal used a float confidence 0.0–1.0, but the codebase already standardised on a `Confidence` enum (low/medium/high). Aligned to the enum rather than introducing a second representation. Then wrote 14 specs red, implemented `app/workspace/{store,sections}.py` to green, full suite **57/57**, zero regressions.
- **Design payoff:** Because the reasoning engine already emits a structured `Investigation`, the Workspace is just *persist + history + index over that object* — clean seam, no reshaping. Sections are a registry (one-line append to add one), so personas and artifacts (next steps) transform over the same state.
- **Living-document property is real:** append-only snapshots (nothing overwritten), a `test_persists_across_store_instances` spec proves it's genuine SQLite state (not chat-derived), and confidence-over-time is queryable per hypothesis via a text-normalised key.
- **Next:** wire `/api/chat` to a per-session Workspace + ReasoningEngine; persona-rendered answers; "show me the evidence".

## 2026-06-26 — Chat endpoint wired (personas + the investigation loop)
- **Human judgment / direction:** Human said "go ahead and wire the chat endpoint."
- **AI did:** Added `app/personas.py` (registry of the 5 charter personas as config + a deterministic `render()`), `app/copilot.py` (`CopilotSession` joining DataSource + engine + Workspace), wired `/api/chat`, and updated the UI for evidence disclosure + persona-switch. 14 specs test-first; full suite **71/71**, zero regressions.
- **Two charter distinctions made concrete in the design — and they fell out cleanly:**
  - *ask vs. re-render.* A question runs a genuine investigation and **appends** a Workspace snapshot; switching persona (empty message) **re-renders the latest snapshot with no LLM call** — proving "facts don't change, only the lens" (§5.1) and saving spend. A test asserts `llm.calls` stays at 1 across a persona switch.
  - *evidence is always available.* Rather than a special "show evidence" round-trip, every reply ships its evidence catalog; the UI just discloses it. Matches §5.8/§6.7 "first-class, always-available" without extra endpoints.
- **Cost-conscious by construction:** persona rendering is deterministic composition over the structured Investigation — no second LLM pass for re-framing. The only spend is the one investigation per genuine question.
- **Graceful keyless degradation:** the session builds lazily; with no `ANTHROPIC_API_KEY` the chat returns a friendly "not configured" message instead of crashing, so the whole suite still runs offline and a non-dev can boot the app before placing keys.
- **Next:** the Incident Summary artifact (registry-driven transform over Workspace state), then README run instructions → Iteration 0 complete.

## 2026-06-26 — Incident Summary artifact (operational output)
- **Human judgment / direction:** Human said "build the Incident Summary artifact next."
- **AI did:** Added `app/artifacts.py` — a registry of `ArtifactSpec`s producing an `ArtifactDocument` (typed sections + `to_markdown()`), wired `CopilotSession.artifact()`, `/api/artifact`, and a "Generate Incident Summary" UI button. 11 specs test-first; full suite **82/82**, zero regressions.
- **The payoff of the shared Workspace is now visible:** the artifact is a *pure transform* over the same Investigation the chat already produced — a test asserts generating it makes **zero** new LLM calls. Same understanding, reshaped for incident responders, no manual rewriting (exactly §5.10's thesis).
- **Honest reasoning carried through:** the summary picks the *highest-confidence* hypothesis (a test proves the LOW-confidence decoy is excluded), states that confidence, derives severity from the timeline's peak event, and surfaces outstanding questions — it never overstates.
- **Iteration 0 status:** all build items complete; only the README run-instructions remain for the definition of done. The full demo narrative (dashboard/chat → health → changes → timeline → likely cause → evidence → persona switch → generated artifact, all from the living Workspace) is now achievable end-to-end with a key.
