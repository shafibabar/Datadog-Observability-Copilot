# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

This is a **greenfield repository**. As of this writing it contains only the project charter (`OBSERVABILITY_COPILOT_KICKOFF.md`), `README.md`, and `LICENSE` — there is no application code, build tooling, or tests yet. There are therefore no build/lint/test commands to document; the tech stack has not been chosen and is an explicit approval-gated decision (kickoff §9). Read `OBSERVABILITY_COPILOT_KICKOFF.md` in full before doing anything — it is the binding project charter, not background reading.

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
