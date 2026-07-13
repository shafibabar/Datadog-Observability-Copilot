# Monitors Integration: Observability Copilot ↔ ec-conduct-dd-monitors

## Summary

The Observability Copilot now understands questions about monitoring configuration, alerts, and dashboards by integrating knowledge from the **ec-conduct-dd-monitors** Terraform repository.

## What Changed

### 1. Guard Expansion (`app/guard.py`)
- Added monitor-related keywords to `_ONTOPIC_WORDS`: `monitor`, `alert`, `alert rule`, `dashboard`, `notification`, `threshold`, `alarm`, `critical`, `warning`, `terraform`, `configuration`, `channel`, `slack`, `alerting`, `monitoring`
- Monitor questions now pass Stage 1 of the relevance guard and are never rejected with "I can't help with that"

### 2. Monitors Knowledge Base (`app/monitors/`)
Created a new module that:
- **`index.py`**: Scans the Terraform repo to extract:
  - **21 monitors** with their names, module paths, queries, and alert channels
  - **11 dashboards** with their names and descriptions
  - Provides structured `MonitorsIndex` and formatted context via `get_monitors_context()`

### 3. Reasoning Engine Integration (`app/reasoning/engine.py`)
- Added optional `monitors_index` parameter to `ReasoningEngine.__init__()`
- Detects monitor-related questions using regex pattern
- Automatically injects monitors context into the prompt when relevant
- No changes to test behavior—monitoring context only appears for monitor questions

### 4. Copilot Bootstrap (`app/copilot.py`)
- `build_copilot()` now builds the monitors index at startup
- Passes it to the ReasoningEngine for use in investigations

## Behavior

**Before:** 
```
User: "What alerts do we have for the audit service?"
Copilot: "I'm the Observability Copilot — I investigate system health, telemetry, and incidents. 
         I can't help with that..."
```

**After:**
```
User: "What alerts do we have for the audit service?"
Copilot: [Accepts the question, includes monitors context in reasoning]
         → Can describe the audit_event_consumer_failure monitor, its query, alert channels, etc.
```

## Technical Details

### Monitors Index (Live)
- **21 monitors** extracted from `/modules/*/main.tf` 
- **11 dashboards** identified from variables and resource definitions
- Index builds on-demand (no startup overhead if repo unavailable)

### Context Injection
When a user asks about monitors (keywords: `monitor`, `alert`, `dashboard`, `configuration`, etc.):
1. Guard allows the question through (new keywords)
2. `_is_monitor_question()` detects the topic
3. `get_monitors_context()` formats the index as text
4. Context is appended to the user prompt for the LLM

### Example Context (truncated)
```
## Configured Monitors & Dashboards

### Monitors (21 total)

- **audit_event_consumer_failure** [ec.centralised_audit.communication_event_dlt_counter]: Monitor for audit_event_consumer_failure
- **bootstrap_config_cron_failure** [ec.config_curator.]: Monitor for bootstrap_config_cron_failure
- **cdc_cognition_reconciliation_error** [ec.centralised_audit.cdc_cognition_reconciliation_error_counter]: ...
[... 18 more monitors ...]

### Dashboards (11 total)

- **audit**: Datadog dashboard: audit
- **config_curator**: Datadog dashboard: config_curator
- **debezium**: Datadog dashboard: debezium
[... 8 more dashboards ...]
```

## Testing

- **5 new tests** in `tests/test_monitors.py` verify:
  - Index builds successfully
  - Monitors and dashboards have proper structure
  - Context formatting works correctly
- **All 263 tests pass** (was 258 before monitors integration)
- Guard acceptance verified: ✓ 5/5 monitor questions pass

## Files Added/Modified

**Added:**
- `app/monitors/__init__.py` — Module interface
- `app/monitors/index.py` — Index builder and context formatter
- `tests/test_monitors.py` — Integration tests

**Modified:**
- `app/guard.py` — Added monitor keywords
- `app/reasoning/engine.py` — Added monitors context injection
- `app/copilot.py` — Build monitors index at startup

## Future Enhancements

- Extract alert message templates (currently parsed from `.message` fields)
- Link specific metrics in a question to relevant monitors
- Store monitor → dashboard mappings for better discovery
- Add severity/priority levels from monitor definitions
- Support querying specific monitors by name or metric
