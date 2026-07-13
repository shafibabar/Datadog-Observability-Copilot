# Observability Copilot: Quick Reference

## Four Reasoning Categories

| Category | What | Example | Mandatory Fields |
|----------|------|---------|-----------------|
| **Fact** | Observed, grounded | "Cache hit ratio dropped below 0.90" | Evidence IDs |
| **Hypothesis** | Inferred cause | "Cache invalidation caused latency spike" | Supporting + contradicting evidence + missing info |
| **Recommendation** | Proposed action | "Roll back to v2.4.0" | Evidence IDs |
| **Unknown** | Acknowledged gap | "Why did cache logic change?" | — |

## Five Telemetry Sources (Merged Timeline)

| Source | Example | Domain |
|--------|---------|--------|
| **DEPLOY** | "v2.4.1 deployed", "Rollback to v2.4.0" | Change events |
| **METRIC** | "p95 latency 450ms", "Cache hit ratio 0.85" | Platform signals (latency, errors, throughput, resources) |
| **LOG** | "Exception in cache eviction", "DB connection timeout" | Structured logs, error traces |
| **TRACE** | Distributed span, service call timing | Request path breakdown |
| **SUPPORT** | "Checkout is slow" ticket spike | Customer impact signals |

## 11 Workspace Sections

| Section | What | Example Use |
|---------|------|------------|
| Executive Summary | Narrative headline | "Deployment caused latency spike via cache invalidation" |
| Current Health | Observed facts | "API latency elevated", "Cache performance degraded" |
| Timeline | Chronological events | 14:02 Deploy, 14:06 Cache hit ratio drops, 14:12 Latency spike |
| Evidence | Raw telemetry | Full metric series, event details |
| Correlated Signals | Metrics moved together | Cache hit ratio ↓ → Latency ↑ (correlation) |
| Root Cause | Leading hypothesis + alternatives | "New code broke cache eviction" (high confidence, missing: log analysis) |
| Affected Services | Which services changed | checkout-api, redis-cache, orders-db |
| Customer Impact | Support signals | 5 "slow checkout" tickets since 14:06 |
| Next Steps | Proposed actions | 1. Roll back, 2. Investigate cache logic |
| Outstanding Questions | Open threads | Why did eviction logic change? Are other services affected? |
| Confidence | Current confidence per hypothesis | "Cache invalidation: high", "Memory leak: low" |

## Six Personas (Same Investigation, Different Lens)

| Persona | Detail | Vocabulary | Priority Sections | Focus |
|---------|--------|-----------|------------------|-------|
| **Support** | Low | Plain | impact → health → steps | "What do I tell customer?" |
| **SRE** ← default | High | Technical | health → timeline → cause → steps → confidence | "What happened? Why? How sure?" |
| **SWE** | High | Technical | timeline → cause → services → steps | "Which service broke?" |
| **PM** | Low | Plain | impact → steps | "Customer impact? Fix ETA?" |
| **Leadership** | Low | Plain | impact → steps → confidence | "Business impact? When resolved?" |

## Three Confidence Levels

- **LOW** — Weak evidence, plausible but uncertain
- **MEDIUM** — Some evidence, reasonable
- **HIGH** — Strong evidence, well-supported

Confidence is **revisable**: changes as new evidence arrives.

## Scope (Investigation Lens)

```
Environments:  [prod, staging, non-prod, ...]  (multi-select)
Tenants:       [acme, contoso, tenant-x, ...] (multi-select)
Time window:   start — end  (max 7 days)
```

Sticky per conversation, overridable per message.

## Guard: What Gets Through Stage 1 ✓

**Keywords that auto-allow:**
- Core: `latency`, `error`, `metric`, `deploy`, `alert`, `dashboard`, `incident`, `outage`
- Operators: `p50`, `p95`, `p99`, `5xx`, `4xx`, `timeout`, `slow`, `crash`
- Resources: `cpu`, `memory`, `disk`, `cache`, `database`
- Quality: `slo`, `sla`, `anomaly`, `regression`, `degraded`

**Phrases that auto-allow:**
- `root cause`, `error rate`, `hit ratio`, `response time`

**Short follow-ups:**
- ≤4 words when investigation active: "why?", "and the db?", "what's the fix?"

**What gets blocked ✗:**
- Empty/too long (>2000 chars)
- Injection attempts: "ignore instructions", "you are now", "reveal system prompt"
- Off-topic (no keywords, not follow-up, failed classifier)

**What now gets through (NEW):**
- Monitor questions: `monitor`, `alert`, `notification`, `threshold`, `channel`, `terraform`, `config`, `alarm`

## Artifacts (Transforms, Not Invented)

| Artifact | Audience | Content |
|----------|----------|---------|
| **Incident Summary** | Incident-response team | Summary + severity + timeline + cause + steps + questions |
| **Executive Briefing** | Leadership | Impact + ETA (planned) |
| **Customer Communication** | Support/comms | Customer-safe narrative (planned) |
| **Post-Incident Report** | After-action | Root causes, contributing factors, lessons (planned) |
| **Runbook Recommendation** | Automation | High-confidence cause → suggest playbook (planned, gated on confidence) |

## Monitor Knowledge (21 Monitors, 11 Dashboards)

**Indexed from ec-conduct-dd-monitors repo:**
- 21 monitors: `audit_event_consumer_failure`, `debezium_connector_failure`, `quota_manager_error`, ...
- 11 dashboards: audit, config_curator, debezium, indexer, lookback, ...

**Auto-injected** when user asks about monitors/alerts/dashboards.

## Conversation Persistence

- **Workspace:** Append-only investigation state, versioned snapshots
- **History:** Last 6 turns of user/assistant messages
- **Scope:** Current environment/tenant/time window lens
- **Subject:** Auto-derived from first summary

→ Real conversational memory, not reset each turn.

## Evidence Model

Every claim links to evidence by **ID**:

- **Metric evidence** — `met:api.latency.p95` → time series
- **Event evidence** — `evt:e5` → timestamped event

Invalid IDs silently dropped. Facts must exist in real telemetry.

## System Limits

| Limit | Value | Why |
|-------|-------|-----|
| Telemetry window | 7 days max | Bounds token cost |
| Message length | 2000 characters | Prevents injection, bounds context |
| Conversation history | Last 6 turns | Real memory without runaway cost |
| Hypothesis require | Contradicting evidence + missing info | Forces surface of disproof |
| Evidence | Must exist in catalog | No speculation presented as certainty |

## Example Question Flow

```
User:  "Why is checkout-api slow?"
       ↓
Guard: ✓ Keywords: "slow" + "api" → allowed
       ↓
Copilot asks: Which environment/tenant? (scope)
       ↓
User:  prod, acme tenant, last 2 hours
       ↓
Engine: Gathers telemetry, builds evidence catalog, reasons, returns Investigation
       ↓
Copilot [SRE persona]: 
  Summary: "Deployment v2.4.1 → cache invalidation → latency spike"
  Health: "API latency 450ms (up from 50ms baseline)"
  Timeline: 14:02 Deploy, 14:06 Cache hit drops to 0.45, 14:12 Latency spikes
  Cause: "Cache eviction logic broken in v2.4.1 (high confidence, missing: log analysis)"
  Steps: 1. Roll back, 2. Investigate new code
  Questions: Why did eviction logic change? Other services affected?
       ↓
User:  [clicks "show me the evidence"] 
  → Evidence tab shows metric series, event timeline, full log context
       ↓
User:  "Tell me as PM"
  → Copilot rerenders same investigation through PM lens (low detail, no timeline)
       ↓
User:  "Generate incident summary"
  → Artifact: Incident Summary markdown, email-ready
```

## Files to Read for Deeper Understanding

- `app/reasoning/models.py` — Reasoning categories, confidence, evidence, hypotheses
- `app/telemetry/models.py` — Event sources, severity, scope, metrics
- `app/workspace/sections.py` — 11 sections, population functions
- `app/personas.py` — 6 personas, detail/vocabulary rules
- `app/artifacts.py` — Artifact specs, transforms
- `app/guard.py` — Guard keywords, two-stage gate
- `app/monitors/index.py` — Monitor indexing from Terraform repo
- `docs/CONCEPTS.md` — Full reference (this file)
