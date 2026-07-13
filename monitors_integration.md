---
name: monitors-terraform-integration
description: Observability Copilot integrated with ec-conduct-dd-monitors Terraform repo to understand alerting config
metadata:
  type: project
---

## Integration: Observability Copilot ↔ ec-conduct-dd-monitors

**Status**: Complete and tested ✓  
**Commit**: Not yet committed (staged for user)  
**Impact**: Monitor/alert/dashboard questions no longer rejected; context injected automatically

## What Was Added

### Problem Solved
Questions about monitoring configuration were rejected:
> "I'm the Observability Copilot — I investigate system health, telemetry, and incidents. I can't help with that..."

Users couldn't ask about what monitors are configured, alert thresholds, or dashboard URLs.

### Solution
1. **Guard expansion**: Added `monitor`, `alert`, `dashboard`, `notification`, `channel`, `alarm`, `critical`, `warning`, `threshold`, `terraform`, `config` to `_ONTOPIC_WORDS`
2. **Monitors knowledge base** (`app/monitors/index.py`):
   - Scans `/Users/shafibabar/SmarshGitRepos/ec-conduct-dd-monitors` on startup
   - Indexes 21 monitors from `modules/*/main.tf`
   - Indexes 11 dashboards from variable references in `main.tf`
3. **Context injection** in reasoning engine:
   - Detects monitor-related questions
   - Formats monitors index as text
   - Appends to user prompt for LLM

## Implementation Details

### Files Changed
- `app/guard.py` — added monitor keywords to `_ONTOPIC_WORDS`
- `app/reasoning/engine.py` — added `monitors_index` param, `_is_monitor_question()`, context injection to `_build_user_prompt()`
- `app/copilot.py` — calls `build_monitors_index()` in `build_copilot()`

### Files Added
- `app/monitors/__init__.py` — public interface
- `app/monitors/index.py` — index builder (145 lines):
  - `build_monitors_index()` — scans repo, returns `MonitorsIndex`
  - `_extract_monitors()` — parses `modules/*/main.tf` for `datadog_monitor` resources
  - `_extract_dashboards()` — finds dashboard definitions
  - `get_monitors_context()` — formats as markdown for prompt injection
- `tests/test_monitors.py` — 5 new tests (all pass)

### Test Results
- ✓ 263 tests pass (was 258 before)
- ✓ 1 skipped (playwright)
- Guard verification: 5/5 monitor questions accepted

## Live Data

**Monitors indexed**: 21
```
audit_event_consumer_failure, bootstrap_config_cron_failure, cdc_cognition_reconciliation_error,
cognition_reconciliation_communication_event_dlt, data_plane_freeze_window_failure, debezium_connector_behind_source,
debezium_connector_failure, ec_indexer_consumer_failure, freeze_config_cron_failure,
kpi_event_consumer_error, legacy_config_consumer_failure, lookback_initiation_failed,
lookback_no_completion_today, monitored_corpus_above_trendline, monitored_corpus_below_trendline,
pipeline_not_completion_in_time, qualified_comms_failure_rate, quota_manager_metadata_comms_consumer_error,
quota_manager_reconciled_event_consumer_error, remediation_snapshot_event_error_counter,
window_token_not_reconciled_in_time
```

**Dashboards indexed**: 11
```
audit, config_curator, debezium, indexer, lookback, manual_runs, pipeline_qualifier,
policy_evaluator, quota_manager, reporting, surveillance_filter
```

## Next Steps
- [x] Guard accepts monitor questions
- [x] Monitors indexed on startup
- [x] Context injected to LLM
- [x] Tests pass
- [ ] User commits and reviews
- [ ] Deploy to main

## How to Verify
```bash
# Test guard accepts monitor questions
python -c "
from app.guard import evaluate
questions = [
  'What monitors do we have configured?',
  'Tell me about the audit alert',
  'Show me the alert channels',
]
for q in questions:
    v = evaluate(q)
    print(f'{'✓' if v.allowed else '✗'} {q}')
"

# Test monitors are indexed
python -c "
from app.monitors.index import build_monitors_index
i = build_monitors_index()
print(f'Monitors: {len(i.monitors)}, Dashboards: {len(i.dashboards)}')
"

# Run tests
pytest tests/test_monitors.py -v
pytest tests/ -q
```

## Configuration
- Hardcoded repo path: `/Users/shafibabar/SmarshGitRepos/ec-conduct-dd-monitors`
- Could be made configurable via `MONITORS_REPO_PATH` env var if needed
- Index builds once at startup; gracefully handles missing repo (returns empty index)

## Limitations & Future Work
- Index is static (built at startup, not refreshed when repo changes)
- Dashboard extraction could be improved (currently heuristic-based)
- Alert message templates not yet extracted (could show example alerts)
- No metric → monitor linkage yet (could auto-suggest relevant monitors for a failing metric)
