# GLOSSARY.md — terms & domain model

## Core concepts
- **Investigation Workspace** — the living, persisted, versioned document that *is* the AI's current understanding of an incident. Personas render *from* it; the chat reads/writes *to* it; artifacts serialize *from* it. Append-with-history so prior reasoning stays visible.
- **Reasoning object** — a structured claim carrying: `claim`, `category`, `confidence`, and `evidence` pointers. The atomic unit the workspace and narrative are built from.
- **Category** — every statement is one of: **Fact** (observed), **Hypothesis** (inferred), **Recommendation** (suggested action), **Unknown** (acknowledged gap). Never present speculation as certainty.
- **Confidence** — a level attached to each reasoning object, derived from and traceable to evidence (never asserted arbitrarily); revisable as evidence changes.
- **Evidence** — the underlying telemetry/event a claim points to. Every conclusion must be drillable down to evidence ("show me the evidence").
- **Hypothesis** — a candidate root cause with for-evidence, **against-evidence**, missing-information, and confidence; multiple can be ranked at once; retirable as evidence changes.

## Personas (registry-driven; change the lens, never the facts)
support · sre · swe · pm · leadership. Each = config of which concerns to surface first, vocabulary level, detail depth (`app/personas.py` `REGISTRY`). `render(persona, investigation)` deterministically composes the reply from the structured Investigation — no LLM call, so switching persona re-frames the same facts for free.

## Copilot (`app/copilot.py`) — conversation-aware
Joins DataSource + ReasoningEngine + Workspace and manages **multiple conversations**. Methods take a `conversation_id`. `ask()` = persist user turn + investigate **with recent-turn memory** + append a Workspace snapshot + persist assistant turn; `rerender()` = re-render latest snapshot through a new persona (no LLM); `artifact()` = serialize an artifact (no LLM). `new_conversation`/`list_conversations`/`get_conversation` manage threads. Factory: `build_copilot(settings)` (was `build_default_session`).

## Conversation
A conversation = one Investigation **Workspace** + its persisted **messages** (user/assistant turns) + a title + recency. Survives restart; listed/switched in the UI sidebar. Conversational **memory** = the last N turns (default 6) fed into the reasoning prompt. Persona switches and artifacts are NOT stored as messages (history = real Q&A only).

## Section serializer (`serialize_sections`)
Type-dispatched transform from the rendered Workspace sections into JSON (`kind`: text/claims/list/tags/timeline/evidence/hypotheses/kv) for the live Workspace panel.

## Artifacts (registry-driven transforms over workspace state)
`app/artifacts.py` `REGISTRY` of `ArtifactSpec` → `ArtifactDocument` (typed sections + `to_markdown()`). Pure transform over the Investigation — generating one makes no LLM call. **Incident Summary** built (Iter 0): summary · severity (peak timeline event) · timeline · likely cause (highest-confidence hypothesis) · recommended next steps · outstanding questions. Deferred: Executive Briefing · Technical Investigation Report · Customer Communication Draft · Post-Incident Report · Runbook Recommendation (confidence-gated).

## LLM backend (`LLMClient` seam, `app/reasoning/llm.py`)
Two real implementations behind the seam (tests inject a fake): **`ClaudeCliClient`** — the "Claude Code way", shells out to the local `claude` CLI headless (no API key, uses the Claude Code login) — and **`AnthropicClient`** — the Anthropic SDK (needs `ANTHROPIC_API_KEY`). `COPILOT_LLM_BACKEND` = `auto` (CLI when keyless, else SDK) / `cli` / `sdk`. `build_copilot` returns None (chat degrades) only when neither is available.

## Data
- **DataSource** — interface over telemetry. Adapters: **ReplayAdapter** (scripted synthetic incident) and **LiveDatadogAdapter** (read-only Datadog REST).
- **Datadog auth** — a **Personal Access Token** (`DATADOG_ACCESS_TOKEN`, sent as `Authorization: Bearer`) is preferred; the legacy `DD-API-KEY` + `DD-APPLICATION-KEY` pair is kept as a fallback.
- **Event model** — normalized timestamped event (deploys, metric threshold crossings, log spikes, trace anomalies, support signals) merged into one ordered **timeline**.
- **Canonical demo incident** — deployment-induced latency: deploy → cache hit ratio drop → DB latency up → API SLO breach → support tickets → rollback → recovery.
