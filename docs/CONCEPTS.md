# Observability Copilot: Core Concepts & Understanding

The Observability Copilot is built on a structured conceptual model that constrains what it investigates, how it reasons, and what it delivers. This document maps all first-class concepts.

## Reasoning Model

### Four Reasoning Categories

Every conclusion the copilot produces falls into one of these categories:

1. **Fact** — Observed, grounded in telemetry evidence
   - "Cache hit ratio dropped below 0.90"
   - "Deployment of v2.4.1 completed at 14:06"
   - Linked to evidence catalog

2. **Hypothesis** — Inferred explanation, with *mandatory* contradicting evidence and missing information
   - "Cache invalidation in the new deployment caused the latency spike"
   - Supporting evidence, contradicting evidence, and what would disprove it are all required
   - Core mechanism to prevent speculation presented as certainty

3. **Recommendation** — Suggested actions
   - "Roll back to v2.4.0 to restore baseline latency"
   - "Investigate cache eviction logic in v2.4.1"
   - Evidence-backed, actionable

4. **Unknown** — Acknowledged gaps
   - "Why did the cache eviction logic change?"
   - "Are other services affected by the same deployment?"
   - Explicit declaration of what's not understood

### Confidence Levels

Each conclusion carries confidence:
- **LOW** — Weak evidence, plausible but uncertain
- **MEDIUM** — Some evidence, reasonable but not confirmed
- **HIGH** — Strong evidence, well-supported

Confidence is **revisable** — can change as new evidence arrives in conversation follow-ups.

## Telemetry Model

The copilot normalizes all signals into five event source types, merged into a unified ordered timeline:

### Event Sources

1. **DEPLOY** — Version changes, rollouts, rollbacks
   - "Deployment initiated"
   - "Rollback to v2.4.0"
   - Signals change (risk window)

2. **METRIC** — Performance signals from the platform
   - Latency (p50, p95, p99)
   - Error rates (4xx, 5xx)
   - Throughput (RPS, QPS)
   - Resource usage (CPU, memory, disk)
   - Cache hit ratio
   - Database query latency

3. **LOG** — Application and infrastructure logs
   - Error messages
   - Exception traces
   - Structured logging

4. **TRACE** — Distributed tracing
   - Request spans
   - Service dependencies
   - Timing breakdown

5. **SUPPORT** — Customer-facing signals
   - Support ticket spikes
   - Customer complaints
   - Direct customer impact reports

### Event Severity

- **INFO** — Routine observation, baseline
- **WARNING** — Degradation, threshold crossed, investigate
- **CRITICAL** — Outage, SLA breach, immediate action needed

Events are timestamped and linked to services, enabling timeline reconstruction and correlation.

### Scope (Investigation Lens)

Investigations operate within a **scope**: which environments/tenants to inspect and over what time window.

- **Environments** — prod, non-prod, staging, etc. (multi-select)
- **Tenants** — customer namespaces (multi-select)
- **Time window** — start to end date (capped at 7 days to bound token cost)

Scope is persisted per conversation and overridable per message.

## Workspace Model (Structured Investigation State)

The **Investigation Workspace** is the architectural center — a *living document*, not chat-derived. It structures the investigation into 11 sections:

### Sections (Registry-Driven)

1. **Executive Summary** — High-level narrative (50 words)
   - Generated from investigation, not hard-coded

2. **Current System Health** — Observed facts about the system
   - Facts with confidence levels
   - Plain claims: "API latency is elevated", "Cache performance is degraded"

3. **Timeline of Events** — Chronologically ordered observations
   - All events from all sources merged and sorted
   - Enables pattern recognition and correlation

4. **Observed Evidence** — Full evidence catalog
   - Metric series with time windows
   - Event records with full context
   - Clickable for detailed inspection

5. **Correlated Signals** — Metrics showing causality
   - Which metrics moved together
   - Identifies confounded factors
   - Drives hypothesis formation

6. **Root Cause Hypotheses** — Leading explanations
   - Each hypothesis has:
     - Statement: "Cache invalidation caused latency spike"
     - Confidence: low/medium/high
     - Supporting evidence (IDs)
     - Contradicting evidence (IDs)
     - Missing information (what would resolve it)

7. **Affected Services** — Services with observed changes
   - Extracted from event metadata
   - Scoped by time window

8. **Customer Impact** — Support-sourced signals
   - "Customer support tickets increased"
   - "Spike in 'checkout is slow' tickets"
   - Direct evidence of user-facing impact

9. **Recommended Next Steps** — Proposed actions
   - Rollback, restart, investigate component
   - Prioritized by evidence
   - Gated by confidence threshold (for future runbook recommendations)

10. **Outstanding Questions** — Open threads
    - Declared unknowns
    - Each hypothesis's missing information
    - Drives interactive follow-up

11. **Confidence Assessment** — Current confidence over each hypothesis
    - Tracks confidence movement across turns
    - Answers: "Are we more certain now?"

All sections are **pure transforms** from the Investigation, deterministic and cached (no LLM calls to re-render).

## Concept: Evidence

Every claim is grounded in evidence by **ID**. Evidence catalog entries point to:

- **Metric evidence** — Time series with specific metric name (e.g., "api.latency.p95")
- **Event evidence** — Timestamped, sourced events (deploys, logs, tickets, etc.)

Invalid evidence IDs (cited but missing) are silently dropped — the model cannot surface support that isn't in real telemetry. This enforces grounding.

## Persona Model (Rendering Lenses)

**Same investigation, different lens.** Each persona is configuration (detail level, vocabulary, section priority), never changes the underlying facts.

Five personas:

1. **Support Engineer**
   - Detail: LOW
   - Vocabulary: PLAIN
   - Priority: customer_impact → current_health → next_steps
   - Focus: "What do I tell the customer?"

2. **Site Reliability Engineer (SRE)** ⬅️ Default
   - Detail: HIGH
   - Vocabulary: TECHNICAL
   - Priority: current_health → timeline → root_cause → next_steps → confidence
   - Focus: "What happened and why? How confident are we?"

3. **Software Engineer (SWE)**
   - Detail: HIGH
   - Vocabulary: TECHNICAL
   - Priority: timeline → root_cause → affected_services → next_steps
   - Focus: "Which service broke and what changed?"

4. **Product Manager (PM)**
   - Detail: LOW
   - Vocabulary: PLAIN
   - Priority: customer_impact → next_steps
   - Focus: "How many customers affected? What's the fix?"

5. **Engineering Leadership**
   - Detail: LOW
   - Vocabulary: PLAIN
   - Priority: customer_impact → next_steps → confidence
   - Focus: "Business impact and recovery ETA?"

Each persona surfaces different sections first and adjusts verbosity (e.g., "confidence level: high" shown for technical personas, hidden for non-technical).

## Artifact Model (Operational Outputs)

Artifacts are **transforms over the Investigation state** — they reshape findings for specific audiences and invent nothing. Registry-driven: append a new artifact spec to add a new type.

### Current Artifacts

1. **Incident Summary** — For incident-response teams
   - Summary, severity, timeline, likely cause, next steps, outstanding questions
   - Markdown format, email-ready
   - Future: gated on hypothesis confidence threshold

### Future Artifacts (Designed, Not Yet Implemented)

- **Executive Briefing** — For leadership (impact + ETA)
- **Customer Communication Draft** — For comms team (plain English, timeline, status)
- **Post-Incident Report** — For after-action (findings, contributing factors, lessons)
- **Runbook Recommendation** — For automation (if high-confidence root cause, suggest playbook)

## Monitoring & Configuration Model (NEW)

The copilot now understands alerting configuration from the **ec-conduct-dd-monitors** Terraform repo:

### Monitors (21 indexed)
- Alert name, metric query, severity, alert channel
- Examples: `audit_event_consumer_failure`, `debezium_connector_failure`, `quota_manager_error`
- Automatically injected into reasoning when user asks monitor-related questions

### Dashboards (11 indexed)
- Dashboard name, URL, purpose
- Examples: audit, config_curator, debezium, policy_evaluator

When user asks "What monitors are we running?" or "How are we alerting on X?", the copilot can describe configured monitors, their thresholds, and alert channels.

## Guard Model (Relevance & Abuse)

Two-stage gate before reasoning starts:

### Stage 1: Deterministic (Zero Tokens)
✓ Allow if:
- Mentions clear observability keywords: `latency`, `error`, `deploy`, `alert`, `metric`, `dashboard`, `incident`, `outage`, `slowness`, `crash`, etc.
- Short in-context follow-up ("why?", "and the db?") when investigation already active
- Clearly phrased questions about system health

✗ Block if:
- Empty or over-length message
- Injection/role-hijack attempt ("ignore instructions", "you are now", etc.)

### Stage 2: Hybrid (Optional Classifier)
For ambiguous messages:
- Consult a cheap LLM classifier (if available)
- Fail closed: if classifier unavailable, refuse the question
- Ensures only genuine observability questions reach the expensive reasoning pass

**Never rejected:** Monitor/alert/dashboard/configuration questions (keywords now pass Stage 1).

## Query Model (Scope + Question)

A query is:

```
question (string) +
scope (environments, tenants, time window)
```

The scope is:
- Persisted per conversation (sticky)
- Overridable per message
- Translated by each DataSource into its own query filter
- Capped at 7 days to bound token cost

Example: 
```
Q: "Why is checkout-api slow?"
Scope: environments=[prod], tenants=[acme], start=now-2h, end=now
```

## Conversation Model

Conversations are **first-class, persistent entities** with:

- **Workspace** — living investigation state (append-only, versioned)
- **Message history** — user/assistant turns (real memory for follow-up)
- **Scope** — current lens (environment, tenant, time window)
- **Subject** — auto-derived from first investigation summary

New messages feed prior turns as history to the reasoning engine → real conversational memory, not each-turn reset.

## Topic Understanding (Keywords & Triggers)

The guard recognizes and allows these topics through immediately:

### Observability Keywords
`latency`, `p50`, `p95`, `p99`, `deploy`, `deployment`, `rollback`, `slow`, `slowness`, `error`, `errors`, `5xx`, `4xx`, `timeout`, `healthy`, `health`, `unhealthy`, `cpu`, `memory`, `disk`, `throughput`, `rps`, `qps`, `traffic`, `incident`, `outage`, `downtime`, `slo`, `sla`, `trace`, `traces`, `span`, `metric`, `metrics`, `dashboard`, `spike`, `spiking`, `saturation`, `cache`, `database`, `api`, `endpoint`, `service`, `alert`, `anomaly`, `regression`, `degraded`, `crash`, `restart`

### Monitor & Configuration Keywords (NEW)
`monitor`, `monitors`, `alerting`, `alert`, `alerts`, `notification`, `notifications`, `channel`, `slack`, `threshold`, `trigger`, `alarm`, `critical`, `warning`, `terraform`, `configuration`, `config`, `alert rule`, `monitoring`

### Phrases (High Signal)
`root cause`, `error rate`, `hit ratio`, `response time`

## System Boundaries & Constraints

- **Telemetry window:** max 7 days (per scope, bounds token cost)
- **Message length:** max 2000 characters (prevents injection, bounds context)
- **Conversation history retained:** last 6 turns (real memory without runaway token cost)
- **Evidence validation:** invalid citations silently dropped (facts must exist in real data)
- **Confidence:** never inflated; hypotheses require contradicting evidence fields
- **Grounding:** every claim cites evidence IDs; no speculation presented as certainty

## In One Paragraph

The Observability Copilot is a **reasoning engine over normalized telemetry** that structures findings into a **living workspace** with canonical sections (health, timeline, root cause, customer impact, etc.), surfaces conclusions in four categories (fact/hypothesis/recommendation/unknown) each with confidence and evidence, renders answers through **six interchangeable personas** (support, SRE, SWE, PM, leadership), emits **operational artifacts** (incident summaries, future: runbooks, post-mortems), operates within a **scoped lens** (which environments/tenants, what time window), accepts **monitor/alert configuration questions**, and refuses off-topic or injection attempts before the expensive reasoning path runs. Every conclusion is evidence-backed, confidence is revisable, and the workspace persists as a real investigation document across conversation turns.
