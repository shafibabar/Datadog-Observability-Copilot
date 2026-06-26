# ROADMAP.md

## Iteration 0 — MVP slice (current)
The smallest coherent, demoable, extension-ready slice.
- [x] Foundation: config/secrets, FastAPI app, chat UI skeleton, context files.
- [x] TDD harness + foundation test baseline (11/11 green).
- [x] `DataSource` interface + **ReplayAdapter**: canonical synthetic incident (deployment-induced latency: deploy → cache hit ratio drop → DB latency up → API SLO breach → support tickets → rollback → recovery). Normalized timestamped event model.
- [x] **LiveDatadogAdapter** (read-only): metrics + events via Datadog REST API (HTTP mocked in tests). Monitors deferred.
- [x] **Reasoning engine** (Claude): structured reasoning objects (claim · category Fact/Hypothesis/Recommendation/Unknown · confidence · evidence pointers); automatic timeline reconstruction; root-cause hypotheses with for/against evidence + missing info. Evidence-grounded (invalid citations dropped). Claude mocked in tests.
- [x] **Investigation Workspace** (SQLite, append-with-history): immutable snapshots of the full Investigation; queryable reasoning objects; confidence-over-time per hypothesis; 11 registry/config-driven sections (`app/workspace/sections.py`). Real persistence proven across store instances. No secrets in DB.
- [x] Chat wired to workspace + reasoning (`app/copilot.py` CopilotSession); **persona-rendered** answers (registry-driven personas in `app/personas.py`); "show me the evidence" ships with every reply; persona-switch re-renders the same facts with no new LLM call. Graceful keyless degradation.
- [x] One artifact: **Incident Summary** (`app/artifacts.py`: transform over workspace state; `ArtifactDocument` → markdown; `/api/artifact` + UI button). Registry-driven artifact set (append an `ArtifactSpec` to add more). Picks highest-confidence hypothesis; severity from timeline; grounded (no invention).
- [x] README run instructions a non-developer can follow verbatim (setup, key placement, run, demo walkthrough, tests, live Datadog, troubleshooting). Boot verified via smoke test.

**✅ Iteration 0 COMPLETE (2026-06-26)** — definition of done met; 82/82 tests green; runnable end-to-end.

**Definition of done (Iteration 0):** dashboard-tab + copilot-tab story works end to end: activate → health summary → significant changes → timeline → likely cause → evidence → persona-adapted explanation → one generated artifact, backed by the living Workspace, runnable locally.

## Iteration 1 — conversations, memory, UI (done 2026-06-26)
- [x] **Multiple conversations** (backend + frontend): conversation = Workspace + persisted messages; sidebar to list/create/switch; survives restart.
- [x] **Conversational memory**: bounded recent-turn history fed to the reasoning prompt so follow-ups carry context.
- [x] **New 3-pane UI**: conversation sidebar · restyled chat (markdown + evidence disclosure) · collapsible **live Investigation Workspace panel** (sections re-render each turn; confidence/severity color vocabulary).
- [x] Conversation-scoped API; `Copilot` service; `serialize_sections`. 113 tests, 99% coverage.
- Deferred within this theme: persist per-message evidence (reload disclosure); conversation rename/delete in UI.

## Later iterations (deferred, seams in place)
- More artifacts: Executive Briefing, Customer Communication Draft, Technical Investigation Report, Post-Incident Report, Runbook Recommendation (confidence-gated, evidence-cited).
- More personas; deeper continuous/proactive reasoning.
- More Datadog signals: logs, traces/APM, SLOs/error budgets.
- Stubbed downstream integrations (ticketing/comms/incident mgmt) behind clean adapter interfaces.
- Secret management via Vault/Okta (swap at `app/config.py`).
- UI polish; deploy/share path if desired.
