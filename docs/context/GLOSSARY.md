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

## CopilotSession (`app/copilot.py`)
Joins DataSource + ReasoningEngine + Workspace into the chat loop. `ask()` = investigate + append a Workspace snapshot (living doc grows); `rerender()` = re-render latest snapshot through a new persona, no new reasoning. Every reply ships its evidence catalog.

## Artifacts (registry-driven transforms over workspace state)
Incident Summary (Iter 0) · Executive Briefing · Technical Investigation Report · Customer Communication Draft · Post-Incident Report · Runbook Recommendation (confidence-gated).

## Data
- **DataSource** — interface over telemetry. Adapters: **ReplayAdapter** (scripted synthetic incident) and **LiveDatadogAdapter** (read-only Datadog REST).
- **Event model** — normalized timestamped event (deploys, metric threshold crossings, log spikes, trace anomalies, support signals) merged into one ordered **timeline**.
- **Canonical demo incident** — deployment-induced latency: deploy → cache hit ratio drop → DB latency up → API SLO breach → support tickets → rollback → recovery.
