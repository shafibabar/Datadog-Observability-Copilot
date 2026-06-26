# Kickoff Prompt — Observability Copilot: From Dashboards to Decisions

> **Read this whole document before responding. This is your project charter and our working agreement. Do not start writing code in your first response. Your first deliverable is a plan, not an implementation.**

---

## 1. How to read this document

You (Claude Code) are being handed a project. This file gives you:

1. The **operating model** — how you and I will work together. This is the most important section. Read it first and treat it as binding.
2. The **product vision** — what we are building and why.
3. The **capabilities and scope** — what the system should eventually do.
4. The **engagement scope** — how much of it we are actually building now, and the bar for "good enough to hand back."
5. **What I expect from your first few responses.**

If anything in the operating model conflicts with a natural coding instinct you have (e.g. "just scaffold it and show the user"), the operating model wins. Ask first.

---

## 2. Operating Model (read carefully — this is non-negotiable)

**I am a non-coding partner. I will not write, edit, or debug any code at any point in this project.** Please internalize this. Every workflow you design, every instruction you give me, and every assumption you make should be built around the fact that the human in this loop does not code.

### What you own

You are responsible for **all technical execution**, including:

- Producing the plan, the architecture/design, and the roadmap.
- Writing **100% of the code** — application code, configuration, tests, scripts, schemas, mock data generators, everything.
- Choosing the tech stack, frameworks, and libraries, and justifying those choices to me for approval.
- Resolving all dependencies, version conflicts, and build/tooling issues yourself.
- Installing or specifying any approved third-party software or libraries (you propose, I approve before anything is added).
- Integration between components and any external/mock services.
- Writing the run instructions so clearly that a non-developer can follow them literally, step by step, with zero inference required.

### What I own

I will only do the following, and only when you give me **exact, copy-pasteable instructions**:

- **Approvals** — I approve plans, designs, tech-stack choices, library additions, and scope changes. Nothing significant proceeds without my explicit "approved."
- **Repo creation** — I will create the repository when you tell me the platform, the exact name, the visibility, the folder structure, and the initial commands. Spell it all out.
- **Commits** — I will run the commit/push commands you give me. Provide the exact commands and commit messages.
- **Running things locally / pasting output back** — I can run commands you give me and paste the results (terminal output, errors, screenshots) back to you so you can diagnose.
- **Account/key setup** — if a service or API key is needed, you walk me through obtaining and placing it. You never assume I know where things go.

### Rules of engagement

1. **Plan before code.** Always. We move through approval gates: **Plan → Design → Roadmap → (my approval) → Implementation, iteration by iteration.**
2. **Never assume I know developer conventions.** Don't say "add it to your PATH" or "set up your venv" without the literal commands and where to type them.
3. **One clear action at a time when I need to act.** When you need something from me, state it explicitly, numbered, with exact commands. Don't bury an action item inside prose.
4. **Propose, don't silently decide,** for anything that adds a dependency, changes architecture, or affects cost/security. Give me the recommendation, the alternatives, the trade-off, and a default you'd pick — then wait for approval.
5. **If you're blocked on a decision that's mine to make, ask.** Don't guess on scope, stack, or anything requiring an approval.
6. **Surface assumptions.** When you must assume something to keep moving, label it clearly as an assumption so I can correct it.
7. **Keep me oriented.** At the end of each working session, tell me: what got done, what's next, and what (if anything) you need from me to proceed.
8. **Persist all context to files (see "Project Memory" below).** Nothing important may live only in chat. If a decision, assumption, fact, or piece of state matters, it must be written to the structured context files and committed. This is non-negotiable.

### Project Memory & Context Continuity (NON-NEGOTIABLE — this has to be taken care of)

**Why this exists.** This project will span multiple sessions, and may be resumed on a different machine or even a **different person's Claude account**. To keep **token and dollar costs under control** and to **prevent hallucination and context drift**, the project's full working context must live in a small set of **structured, human-readable, version-controlled files committed to the repo** — never only in conversation history. These files are the single source of truth. Chat is disposable; the files are durable.

**The mechanism.** Maintain a dedicated context directory in the repo (propose the exact layout for my approval — e.g. `/.project-context/` or `/docs/context/`). A reasonable starting set, which you should refine:

- **`PROJECT.md` (entry point / "read me first").** A concise orientation any fresh session reads before doing anything: the vision in brief, the operating model summary (I never code; approval gates), hard constraints, the approved tech stack, and explicit "how to resume this project" instructions. This file plus this kickoff prompt should be enough for a brand-new session — on any account — to pick up with zero hidden context.
- **`STATE.md` (current status).** The live snapshot: what is done, what is in progress, what is next, and which approval gate we're at. Updated every session.
- **`DECISIONS.md` (decision log / lightweight ADRs).** Every significant decision with the date, the choice, the alternatives considered, and the reason. This is what stops us re-litigating settled questions and re-spending tokens deriving them again.
- **`ROADMAP.md` (plan / backlog).** Iterations, what's in each, what's deferred (cross-reference §8).
- **`BUILD-LOG.md` (the journey).** The running narrative of how the solution came together — this directly serves the presentation's meta story (§7.2). What was fast, what was hard, where AI accelerated things, where human judgment was required.
- **`GLOSSARY.md` / domain model summary.** Key terms, the workspace data model, persona/artifact registries (cross-reference §5.9/§5.10), so the AI re-grounds on the actual model rather than guessing.
- **`OPEN-QUESTIONS.md`.** Unresolved questions and things awaiting my input, so nothing is silently dropped or re-invented.

**Operating protocol (follow every session):**

1. **Start of session:** read the context files (at minimum `PROJECT.md` and `STATE.md`) before taking any action, and re-ground on them. Treat the files as **authoritative over your own recollection** — if your memory and the files conflict, the files win.
2. **During the session:** when a decision is made, an assumption is taken, or state changes, write it to the appropriate file as you go.
3. **End of session (and at each milestone):** update `STATE.md`, `DECISIONS.md`, `BUILD-LOG.md`, and `OPEN-QUESTIONS.md` as needed, then give me the exact commit commands so the updated context is committed alongside the code.
4. **Token/cost discipline:** keep these files **concise and structured** — summaries, decisions, and pointers, not transcripts or dumps. Prefer reading the relevant context file over re-reading the entire codebase. The goal is the cheapest reliable way to fully re-establish context, not maximal verbosity.
5. **Portability test:** at any point I should be able to hand this repo plus this kickoff prompt to a fresh Claude session on a different account and have it resume correctly. Periodically sanity-check that this is still true and flag me if context has leaked into chat-only memory.

When you propose the plan (§10) and the design (§9), include this context-file structure as an explicit deliverable, and set it up as one of your very first actions so it accumulates from day one rather than being reconstructed later.

---

## 3. Project Vision

We are building an **AI-powered Observability Copilot** — an intelligent reasoning layer that sits **on top of** existing observability data and turns raw telemetry into human understanding and operational decisions.

**This is not another chatbot. This is not another dashboard.** It is an intelligent investigative assistant that behaves like an experienced Site Reliability Engineer sitting beside the user.

Modern observability platforms emit enormous amounts of telemetry but assume deep domain expertise. Support engineers, PMs, QA, Customer Success, and many software engineers struggle to interpret dashboards, judge what's significant, correlate events, and decide what to do. This project reduces that cognitive burden by letting AI **explain, investigate, correlate, summarize, and guide.**

### The core shift

Dashboards answer *"What is the CPU utilization? What is the latency? How many errors?"*

Users actually want answers to *"Is the system healthy? Is this expected? What changed? Why did this happen? Which service is responsible? Are customers impacted? Is this an incident? Should I escalate? What do I investigate next?"*

Today users must mentally correlate dozens of charts, events, deployments, logs, traces, and metrics to reach a conclusion. **The Copilot should perform that reasoning automatically.**

### Guiding principle

> Monitoring tells you *what* happened. Observability helps you understand *why*. This project demonstrates how AI helps organizations decide *what should happen next.*

The product lifecycle to embody: **Observe → Understand → Investigate → Explain → Recommend → Execute → Document → Learn.**

---

## 4. Core Philosophy (design every feature against these)

- Instead of exposing metrics, **explain** them.
- Instead of showing graphs, **tell the story.**
- Instead of displaying anomalies, **investigate** them.
- Instead of overwhelming users, **progressively reveal** insights.
- Every interaction should **reduce** complexity.
- Every conclusion must carry **supporting evidence.**
- The AI must clearly distinguish **Facts vs. Hypotheses vs. Recommendations vs. Unknowns.** Users must always know which statements are observed and which are inferred. Never present speculation as certainty.

---

## 5. Capabilities the system should eventually demonstrate

Treat this as the full target picture. We won't build all of it (see §8), but the architecture must accommodate all of it. Each subsection below states **what the capability is**, **why it matters**, and the **design implications** you should carry into the architecture even when the feature itself is deferred.

### 5.1 Persona-aware explanation

**What it is.** The same underlying telemetry and the same investigation can be explained very differently depending on who is asking. The AI tailors the depth, vocabulary, framing, and the *set of concerns it leads with* to the user's role. The user can switch persona at any time ("explain this to a Support Engineer," "now summarize for executives") and the explanation re-renders from the same evidence — the facts don't change, only the lens.

**Why it matters.** A single observability story has to serve audiences with wildly different mental models and goals. Forcing everyone through the same SRE-grade explanation is exactly the cognitive burden this project exists to remove.

**Per-persona focus:**

- **Support Engineer** — customer impact, current service health, known issues and their status, escalation guidance, and immediate troubleshooting steps. Avoid deep infrastructure terminology unless explicitly requested; translate internal signals into "what the customer is experiencing."
- **Site Reliability Engineer** — the golden signals (latency, traffic, errors, saturation), SLOs and error-budget burn, infrastructure behaviour, performance bottlenecks, root-cause hypotheses, and concrete recommended investigations. This persona can handle full technical depth and expects it.
- **Software Engineer** — service-level behaviour, recent deployments and what they changed, dependency relationships, runtime anomalies, and potential code regressions. Oriented toward "is my code/service the cause, and what changed."
- **Product Manager** — customer impact, business impact, feature availability, a clear incident summary, user-experience framing, and executive-readable explanations. Minimal infrastructure detail.
- **Engineering Leadership** — overall system health, incident severity, operational risk, business impact, recommended actions, and high-level summaries. Optimized for fast situational awareness and decision-making, not detail.

**Design implications.** Personas must be **data-driven / registry-based**, not hard-coded into prompts or UI branches. Each persona is effectively a configuration: which concerns to surface first, what vocabulary level, how much detail, which workspace sections to emphasize, and which output artifacts are most relevant. New personas should be addable without touching core reasoning. The persona is an input to the *rendering/explanation* layer; it must never alter the underlying facts or evidence.

### 5.2 Continuous reasoning

**What it is.** The AI continuously reasons over the available telemetry rather than only responding to direct questions. It proactively identifies significant changes, trends, correlations, anomalies, potential root causes, operational risks, service dependencies, and customer impact — and attaches a stated **confidence level** to each conclusion, with the supporting evidence linked.

**Why it matters.** Users often don't know the right question to ask. Surfacing "here's what's significant right now and why" is the difference between a dashboard interpreter and an investigative assistant.

**Design implications.** Every reasoning output must be a structured object carrying: the claim, its category (fact/hypothesis/recommendation/unknown — see §4), its confidence, and pointers to the evidence that supports (or contradicts) it. Confidence must be derived from and traceable to evidence, never asserted arbitrarily. This structure is what the Workspace (§5.9) and the artifacts (§5.10) are built on, so get it right early.

### 5.3 Storytelling

**What it is.** The AI converts telemetry into narrative. The goal is prose that reads like an experienced engineer talking, not an automated metric summary.

- **Not:** *"Latency increased from 120 ms to 480 ms."*
- **Instead:** *"Checkout latency began increasing approximately 12 minutes after the latest deployment. At the same time, database response times increased while cache efficiency declined. Error rates remain stable, suggesting customers are currently experiencing slower responses rather than failures."*

**Why it matters.** Narrative encodes causality, sequence, and significance — the exact things a wall of charts forces the human to reconstruct manually.

**Design implications.** Narratives must be generated *from* the structured reasoning objects (§5.2) and the timeline (§5.5), so every sentence in the story is backed by retrievable evidence. The story should degrade gracefully: when evidence is thin, the prose should hedge honestly ("suggesting," "consistent with") rather than overstate. Storytelling is a presentation concern layered on facts, never a substitute for them.

### 5.4 Investigation model

**What it is.** Every investigation is structured to answer a consistent set of investigative questions, so the AI behaves like a disciplined investigator rather than an ad-hoc responder:

- What happened?
- When did it begin?
- Where is it occurring?
- Which services are involved?
- What changed beforehand?
- What evidence supports the conclusion?
- What is the most likely explanation?
- What remains uncertain?
- What should the user investigate next?

**Why it matters.** A repeatable investigative frame is what makes the assistant trustworthy and consistent across incidents and across users. It also maps directly onto the Workspace sections.

**Design implications.** This question set should be a first-class structure in the domain model — effectively the schema the Workspace and reports are organized around. "What should the user investigate next?" must always be populated, because guiding the next step is a core success criterion.

### 5.5 Automatic timeline reconstruction

**What it is.** Rather than presenting isolated events, the AI reconstructs the operational story as an ordered, causally-linked timeline. Canonical example:

```
09:02  Deployment initiated
  ↓
09:06  New version became active
  ↓
09:08  Cache hit ratio declined
  ↓
09:10  Database latency increased
  ↓
09:12  API response time exceeded SLO
  ↓
09:15  Customer support tickets increased
  ↓
09:20  Rollback initiated
  ↓
09:27  Metrics returned to baseline
```

**Why it matters.** The timeline is often the single most powerful artifact for understanding an incident — users grasp the sequence instantly without correlating dashboards by hand.

**Design implications.** Events from all telemetry sources (deploys, metric threshold crossings, log spikes, trace anomalies, support signals) must be normalized into a common event model with timestamps so they can be merged into one ordered timeline. Each timeline entry should link back to its source evidence. The timeline must be incrementally updatable as new evidence arrives, and it feeds both the narrative (§5.3) and the reports (§5.10).

### 5.6 Root-cause reasoning

**What it is.** The AI attempts causal reasoning, not just observation. For every incident it produces: possible causes, supporting evidence, **contradictory** evidence, a confidence level, alternative hypotheses, and explicitly-listed missing information. It must avoid presenting speculation as certainty.

**Why it matters.** "Why did this happen?" is the question dashboards can't answer and the one users most need answered. Honest hypothesis-with-evidence reasoning is what an experienced SRE actually does — including holding multiple competing hypotheses.

**Design implications.** Hypotheses are structured objects with for/against evidence and confidence, and there can be several ranked simultaneously. The model must be able to *revise* confidence and *retire* hypotheses as evidence changes (this is the engine behind the "living" investigation in §5.9). Contradictory evidence and missing information are required fields, not optional — surfacing what would *disprove* a hypothesis is a feature, not an afterthought.

### 5.7 Interactive, contextual investigation

**What it is.** Users ask follow-up questions in natural language and the AI maintains full conversational context across the entire investigation. Representative questions:

> *Why did this happen? · What changed? · Show me the evidence. · Which service caused this? · What should I investigate next? · Is this customer-impacting? · How confident are you? · Explain this to a Support Engineer. · Explain this to an SRE. · Summarize this for executives. · What happened after yesterday's deployment?*

**Why it matters.** Investigation is iterative. The assistant must feel like it remembers everything discussed, so the user is *building* an investigation rather than re-asking from scratch each turn.

**Design implications.** Context isn't just chat history — it's the full investigation state (§5.9). Each new question reads from and writes to that shared state. "Explain this to <persona>" re-renders existing findings through §5.1; "show me the evidence" drills into the structures from §5.2/§5.8; "how confident are you?" surfaces §5.6 confidence. The conversation is a *view onto* the living investigation, not a separate transcript.

### 5.8 Explainability / transparency

**What it is.** Every insight is explainable. Users can always drill into the evidence, the correlated metrics, the related events, the reasoning chain, and the supporting observations behind any statement.

**Why it matters.** Trust is the adoption blocker for an AI reasoning layer. Users (especially SREs and engineers) will not act on conclusions they can't verify. Transparency converts skepticism into trust.

**Design implications.** Because every reasoning object (§5.2) and hypothesis (§5.6) already carries evidence pointers, the UI must expose a consistent "show the evidence / show the reasoning" affordance on essentially every claim. There should be no dead-end assertions — anything the AI states should be traceable down to the underlying telemetry or event that supports it.

### 5.9 The Investigation Workspace (a defining feature — prioritize this)

**What it is.** This is the feature that most distinguishes the product from a chatbot. **Every interaction contributes to a single, persistent, evolving Investigation Workspace** — a *living document*, not a chat transcript. The AI continuously builds a structured investigation as evidence accumulates and as the user asks questions. The workspace auto-organizes findings into meaningful sections, for example:

- Executive Summary
- Current System Health
- Timeline of Events
- Observed Evidence
- Correlated Signals
- Root Cause Hypotheses
- Affected Services
- Customer Impact
- Business Impact
- Recommended Next Steps
- Outstanding Questions
- Confidence Assessment

**Living behaviour.** Each new observation must **reinforce, contradict, or refine** prior conclusions. As telemetry arrives or new questions are asked, the workspace continuously: updates findings, revises hypotheses, raises or lowers confidence, records newly discovered evidence, flags contradictions, and highlights unresolved questions. **Historical reasoning remains visible** — users can see how a conclusion evolved and why confidence moved. Users should never feel they're starting over with each question; they are collaboratively building an investigation with the AI.

**Why it matters.** The workspace *is* the AI's current understanding of the incident, kept synchronized throughout. It's what turns scattered Q&A into a coherent, auditable investigation and is the substrate every operational artifact (§5.10) is generated from.

**Design implications.** This requires a real, persisted, versioned investigation-state model — not derived on the fly from chat. Sections must be **extensible** (registry/config-driven), since they will grow. The state needs to support append-with-history (so prior reasoning isn't destroyed when revised), confidence over time, and contradiction tracking. Treat the workspace data model as the architectural center of gravity: personas render *from* it, the conversation reads/writes *to* it, and artifacts serialize *from* it. Bring its design to me explicitly (it's called out again in §9).

### 5.10 Operational outputs (artifacts)

**What it is.** Beyond conversational answers, the system serializes the current investigation state into structured artifacts ready for downstream operational workflows:

- **Incident Summary** — a concise operational overview for incident-response teams.
- **Executive Briefing** — a non-technical summary covering customer impact, business impact, and overall operational status.
- **Technical Investigation Report** — a detailed engineering report: timeline, evidence, correlations, hypotheses, confidence levels, and remaining unknowns.
- **Customer Communication Draft** — a customer-friendly explanation that removes internal implementation detail while accurately describing customer impact and recovery progress.
- **Post-Incident Report** — a structured review: timeline, root cause, contributing factors, resolution, preventative actions, and lessons learned.
- **Runbook Recommendation** — when confidence is sufficiently high, the most relevant operational runbook or remediation procedure, always accompanied by supporting evidence and expected outcomes.

**Why it matters.** This is where "explaining a dashboard" becomes "operational intelligence." The same understanding is reshaped for incident responders, executives, engineers, and customers with no manual re-writing — that reuse is the payoff of the shared workspace.

**Design implications.** Each artifact is a **transform over the same workspace state**, differing in audience, included sections, vocabulary, and confidentiality (e.g. the customer draft must strip internal details). Make the artifact set **registry-driven** so new artifact types can be added later. Runbook recommendations must be **gated on a confidence threshold** and must always cite evidence and expected outcome — never recommend a remediation the evidence doesn't support.

### 5.11 Workflow integration philosophy

**What it is.** The AI is an intelligence layer that enhances existing operational processes rather than living in isolation. The outcome of an investigation should transition naturally into downstream workflows: escalating incidents for engineering, creating structured incident records, generating customer-facing comms, preparing executive updates, producing post-incident-review documentation, triggering operational runbooks, supporting change-management decisions, and providing context for future investigations.

**Why it matters.** The long-term vision is an **Operational Intelligence Layer** sitting between telemetry and enterprise operations — the reasoning engine connecting observability to incident management, documentation, customer communication, runbooks, change management, and continuous improvement. The full lifecycle to embody: **Observe → Understand → Investigate → Explain → Recommend → Execute → Document → Learn.** The aim is to minimize the manual effort required to turn operational knowledge into operational action.

**Design implications.** For now, downstream systems are **stubbed adapters behind clean interfaces** — we don't integrate real ticketing/comms/incident tooling yet, but the seams must exist so a real integration drops in without rework. Each integration point should consume the workspace/artifacts (§5.9/§5.10) rather than reaching into internal reasoning, keeping the intelligence layer decoupled from any specific enterprise system.

---

## 6. UX Principles

The interface should feel like an **intelligent analyst**, not a chat application. The **dashboard remains the primary source of truth**; the AI is an *interpretation layer* sitting beside it, not a replacement for it. The overarching goal of every UX decision is the same as the project's: **reduce cognitive load and progressively reveal insight.** Below, each principle is expanded with intent and concrete design implications.

### 6.1 The dashboard stays primary; the AI interprets

The user should never feel the AI has hidden or replaced their data. The traditional dashboard (charts, metrics, events) remains visible and authoritative; the Copilot annotates, explains, and investigates *over* it. **Design implication:** favor a layout where the dashboard and the Copilot/Workspace coexist (e.g. dashboard alongside an investigation panel) rather than a full-screen chat that hides the data. The AI should be able to point back at specific charts/events it's referencing.

### 6.2 Visual clarity

The UI should be calm, legible, and unambiguous — an operations tool, not a toy. Clear hierarchy, restrained color used meaningfully (e.g. severity/health states), and obvious distinction between the four statement categories from §4 (facts vs. hypotheses vs. recommendations vs. unknowns). **Design implication:** establish a small, consistent visual vocabulary for confidence levels, severity, and statement type, and reuse it everywhere. (When you reach UI build, consult the `frontend-design` skill for styling direction.)

### 6.3 Minimal cognitive load

Default to the *least* information needed to orient the user, and let them pull more. Lead with the answer ("the system is degraded; checkout is slow; likely caused by the 09:02 deploy"), not the raw signals. **Design implication:** summaries first, detail on demand; avoid presenting more than one primary conclusion at a time; never dump every metric when one explanation will do.

### 6.4 Progressive disclosure

Insight should unfold in layers: headline → supporting summary → evidence → raw telemetry. The user controls how deep they go. **Design implication:** every conclusion should be expandable down to its evidence (this is the UI expression of §5.8). Collapsed-by-default detail; one click deeper at each level. The Workspace sections (§5.9) should themselves be collapsible so users can focus.

### 6.5 Interactive exploration

The experience is investigative and hands-on, not a static report. Users can drill into any claim, switch personas, ask follow-ups, and watch the Workspace update. **Design implication:** make evidence, hypotheses, timeline entries, and affected services clickable and cross-linked; selecting an event on the timeline should highlight related evidence and the conclusions that depend on it.

### 6.6 Natural conversation

Follow-up questions are asked in plain language and answered in context (§5.7), but the conversation is a *view onto the living investigation*, not a throwaway transcript. **Design implication:** the chat affordance and the Workspace must feel like one connected surface — asking a question visibly enriches the Workspace, and clicking something in the Workspace can seed a question. Avoid a design where chat and the investigation document are disconnected.

### 6.7 Evidence-driven conclusions

Nothing the AI asserts should look like an unsupported opinion. Every conclusion visibly carries its confidence and a path to its evidence. **Design implication:** surface confidence inline with conclusions, visually flag hypotheses vs. facts, and make "show me the evidence" a first-class, always-available action. Honesty about uncertainty (and about unknowns) should be visible, not buried.

### 6.8 Avoid overwhelming users

Concise by default; depth on demand. Prefer tight summaries, then allow deeper exploration — never a wall of text or a screen of simultaneous charts demanding manual correlation. **Design implication:** cap the length of default explanations, chunk long content behind disclosure, and treat "the user had to read a lot to understand the situation" as a UX failure to be designed out.

---

## 7. The Demonstration (this is an internal showcase with TWO objectives)

This demo is being presented internally at my company, and it carries **two intertwined objectives**. You should design and build with both in mind, because they shape different things.

### 7.1 Objective A — the product story (what the audience watches)

Show the progression from traditional observability to AI-assisted operational intelligence: that an AI reasoning layer can turn an intimidating dashboard into a guided, evidence-backed investigation. Target narrative flow:

1. Present a complex monitoring dashboard with many metrics.
2. Show how hard it is for a newcomer to understand the situation.
3. Activate the AI Copilot.
4. AI summarizes overall system health.
5. AI identifies significant changes.
6. AI generates an operational timeline.
7. AI explains likely causes.
8. AI highlights supporting evidence.
9. AI answers audience questions naturally.
10. AI adapts explanations across personas.

The audience should leave feeling they interacted with an experienced engineer, not read a dashboard.

### 7.2 Objective B — the meta story (the real point of the showcase)

**This is the objective that matters most to me, and it changes how we work.** Beyond demonstrating the product, I am presenting **my own learning journey of experimenting with AI implementation** — specifically, demonstrating to my company **how AI can be used to build working solutions quickly, including solutions that are themselves AI-powered.**

The headline I want the audience to take away is: *"A non-developer directed AI to design and build a working, AI-powered solution rapidly — and here is how that was done."* The product is the artifact; the **process is the message**. I do not write any code (see §2); the entire build is driven by me directing Claude Code. That fact is not a limitation to hide — it is the centerpiece of the presentation.

**What this means for you (important):**

- **Treat the build process as a first-class deliverable, not just the product.** Throughout our work, help me capture the journey so it's presentable: the plan/design/roadmap we agreed, the key decisions and why we made them, the approval gates, what was fast vs. what was hard, where AI accelerated things, and where human judgment was still required. A short running "build log" or decision record I can show is valuable — propose a lightweight way to maintain this.
- **Optimize for "quick, credible solution," not "exhaustive product."** The story is *speed and accessibility of AI-assisted development*. Favor choices that are demonstrably fast to stand up, easy for a non-developer to run, and easy to explain — over heavyweight engineering that looks impressive but undercuts the "quick solution" narrative. (This reinforces §8: we build a coherent slice, not the whole thing.)
- **Make the AI-assisted-development angle explicit and repeatable.** Where relevant, surface what made the rapid build possible (e.g. AI handling scaffolding, integration, dependency resolution, generating synthetic data, producing the reasoning prompts) so I can speak to it concretely. The audience should understand this is a repeatable approach they could apply to their own problems, not a one-off.
- **Help me tell the "from zero to working AI solution" arc.** Be ready, when I ask, to help me assemble talking points or a short narrative that walks the audience through how the solution came together and the learnings from the experiment.

### 7.3 How the two objectives fit together

The product demo (A) is the *evidence*; the build-journey narrative (B) is the *thesis*. The thesis is: **AI lets us implement quick, capable solutions — including AI-based ones — and a motivated non-developer can drive it end-to-end.** Every design decision should serve a working, believable product demo **and** keep the build fast, legible, and narratable. If a choice makes the product marginally fancier but the story slower or harder to explain, prefer the simpler, faster, more explainable path.

### 7.4 Build implication for the product demo itself

We need a believable, scripted-but-flexible demo scenario backed by realistic synthetic telemetry (a deployment-induced latency/incident story is the canonical example). Build a data layer that can **replay a known incident** so the live demo is reliable and repeatable, while the AI reasoning over it remains genuine (not hard-coded answers). A reliable, repeatable demo is essential precisely because both objectives are being presented live.

---

## 8. Engagement Scope (important — we are NOT building the whole thing)

**We will not implement the entire product.** We will build a coherent, working slice that proves the concept and is **architected for extension** across future iterations.

Your design must therefore:

- Establish a clean architecture with clear seams: a **telemetry/data layer**, a **reasoning/AI layer**, an **investigation-state layer** (the Workspace), and a **presentation layer** (dashboard + copilot UI).
- Use **synthetic/mock telemetry** for now (you'll generate it), but isolate it behind an interface so a real observability backend (e.g. metrics/logs/traces source) could replace it later without rewrites.
- Treat downstream integrations (incident management, ticketing, comms) as **stubbed adapters** behind interfaces.
- Make the **persona system, the Workspace sections, and the output-artifact types** extensible (config/registry-driven rather than hard-coded), since these will grow.
- Be explicit in the roadmap about what is built now vs. deferred, so future iterations have a clear on-ramp.

When you propose the roadmap, define a small **Iteration 0 / MVP slice** we can actually build and demo, then later iterations layered on top.

---

## 9. Decisions you must bring to me (do not pre-decide)

In your **Design** deliverable, present recommendations + alternatives + a default for at least:

1. **Tech stack** — language(s), framework(s), frontend approach, and why. Optimize for: fast iteration, a polished demo UI, and ease of running locally by a non-developer.
2. **LLM/reasoning approach** — which model/provider, how prompting/orchestration works, how you keep the reasoning grounded in the telemetry and how you enforce the Facts/Hypotheses/Recommendations/Unknowns distinction and confidence scoring. (Assume access to Anthropic's API is available; confirm with me before assuming any specific provider, key, or paid service.)
3. **Investigation-state model** — how the living Workspace is represented, persisted, updated, and versioned so historical reasoning stays visible.
4. **Synthetic telemetry design** — what signals we simulate (metrics/events/deploys/logs/traces), and the canonical demo incident.
5. **Any third-party libraries or services** — listed for approval before installation, with license and cost notes.
6. **Local run + repo strategy** — how I'll run it (ideally one or two commands), and the repo platform/structure you'll have me create.

Do not add any paid service, external dependency, or new tool without my explicit approval.

---

## 10. What I want from your FIRST response

Do **not** write application code yet. Instead:

1. **Confirm** you've understood the operating model (especially: I never code; you produce instructions; we use approval gates; **all context is persisted to structured, committed files, not chat — §2 Project Memory**).
2. Ask me any **clarifying questions** that genuinely block planning (keep them tight and high-leverage). Reasonable examples: my constraints on stack/provider, whether this runs only locally or needs to be deployed/shared, available API keys/budget, and how polished the demo UI must be.
3. Give me a **high-level plan** and a **proposed phased roadmap** (Iteration 0 / MVP, then later iterations), with a clear statement of what the first iteration will and won't include.
4. **Propose the context-file structure** (the Project Memory layout from §2) so we can set it up as the very first thing once the repo exists — it should accumulate from day one.
5. Tell me the **approval gates** you'll use and what you'll need from me at each.

After I approve the plan, proceed to the **Design** deliverable (§9), then to the roadmap detail, and only then — with my approval — to implementation, iteration by iteration. At each implementation step, give me exact commands for repo setup, running, and committing, and tell me what output to paste back.

---

## 11. Definition of done for this engagement

We're in a good place to pause/iterate when:

- There is a **runnable** slice a non-developer can start with copy-paste instructions.
- It demonstrates the core narrative: dashboard → activate Copilot → health summary → significant changes → timeline → likely cause → evidence → persona-adapted explanations → at least one generated operational artifact, all backed by the **living Investigation Workspace**.
- The architecture clearly shows the seams for extension (data source, reasoning, workspace, outputs, integrations) and the roadmap documents what comes next.
- I understand how to run it, commit it, and what each remaining iteration would add.

---

*End of kickoff prompt. Begin with §10.*
