# OPEN-QUESTIONS.md

Unresolved items awaiting human input. Resolve → move the decision to `DECISIONS.md`.

## Open
- **Which real Datadog signals matter most** for your environment (specific metrics, monitors, services)? Needed to make the LiveDatadogAdapter useful on *your* prod. Can default to common golden-signal metrics until specified.
- **Canonical demo incident realism** — is the generic deployment-induced latency story fine, or should the replay mimic a real past incident from your org?

## Resolved
- Run target → local, but able to connect to real production Datadog. (DECISIONS 2026-06-26)
- LLM access → Anthropic key available, cost-conscious mode. (DECISIONS 2026-06-26)
- UI → chat-style, backend as hero. (DECISIONS 2026-06-26)
- Secret handling → gitignored `.env`, never committed. (DECISIONS 2026-06-26)
