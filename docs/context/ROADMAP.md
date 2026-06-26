# ROADMAP.md

## Iteration 0 — MVP slice (current)
The smallest coherent, demoable, extension-ready slice.
- [x] Foundation: config/secrets, FastAPI app, chat UI skeleton, context files.
- [ ] `DataSource` interface + **ReplayAdapter**: canonical synthetic incident (deployment-induced latency: deploy → cache hit ratio drop → DB latency up → API SLO breach → support tickets → rollback → recovery). Normalized timestamped event model.
- [ ] **LiveDatadogAdapter** (read-only): metrics, events, monitors via Datadog REST API.
- [ ] **Reasoning engine** (Claude): structured reasoning objects (claim · category Fact/Hypothesis/Recommendation/Unknown · confidence · evidence pointers); automatic timeline reconstruction; root-cause hypotheses with for/against evidence + missing info.
- [ ] **Investigation Workspace** (SQLite, append-with-history): core sections (Exec Summary, Current Health, Timeline, Evidence, Correlated Signals, Root-Cause Hypotheses, Affected Services, Customer Impact, Recommended Next Steps, Outstanding Questions, Confidence). Registry/config-driven sections.
- [ ] Chat wired to workspace + reasoning; **persona-rendered** answers (registry-driven personas); "show me the evidence" affordance.
- [ ] One artifact: **Incident Summary** (transform over workspace state). Registry-driven artifact set.
- [ ] README run instructions a non-developer can follow verbatim.

**Definition of done (Iteration 0):** dashboard-tab + copilot-tab story works end to end: activate → health summary → significant changes → timeline → likely cause → evidence → persona-adapted explanation → one generated artifact, backed by the living Workspace, runnable locally.

## Later iterations (deferred, seams in place)
- More artifacts: Executive Briefing, Customer Communication Draft, Technical Investigation Report, Post-Incident Report, Runbook Recommendation (confidence-gated, evidence-cited).
- More personas; deeper continuous/proactive reasoning.
- More Datadog signals: logs, traces/APM, SLOs/error budgets.
- Stubbed downstream integrations (ticketing/comms/incident mgmt) behind clean adapter interfaces.
- Secret management via Vault/Okta (swap at `app/config.py`).
- UI polish; deploy/share path if desired.
