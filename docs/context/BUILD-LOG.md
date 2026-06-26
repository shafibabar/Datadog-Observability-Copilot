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
