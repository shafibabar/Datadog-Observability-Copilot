# BUILD-LOG.md — the journey (feeds the presentation meta-story)

Running narrative of how the solution came together: what was fast, what was hard, where AI accelerated, where human judgment was required.

## 2026-06-26 — Kickoff, planning, and foundation
- **Human judgment / direction:** The human (non-developer) supplied the charter and made the high-leverage calls — local run that can still connect to *real* production Datadog; chat-style UI with the **backend as the hero**; cost-conscious LLM use; and the firm constraint that **secrets are never committed** (loaded from an external file during the demo, Vault/Okta later).
- **AI accelerated:** Turned the charter into clarifying questions, a tech-stack recommendation with trade-offs, a phased roadmap, and the full project-memory structure — then scaffolded the foundation (secure config, FastAPI app, chat UI, context files) in one pass.
- **Key insight surfaced:** live Datadog vs. a reliable scripted demo are in tension → resolved cleanly with one `DataSource` interface and two adapters (live + replay). The architecture the charter asked for (clean seams) made this a non-issue.
- **Fast:** dependency choice, secret-handling design, and the chat UI skeleton.
- **Next:** the actual reasoning engine and the living Investigation Workspace — the parts that make it more than a chat box.
