# OPEN-QUESTIONS.md

Unresolved items awaiting human input. Resolve → move the decision to `DECISIONS.md`.

## Open
- **Live Datadog config not taking effect (was reported as ".env not loading").** Diagnosed 2026-07-08: in the repo the `.env` loads fine (correct path, no CRLF/BOM, nothing shadowing) — it's a **contents** issue, the file is the untouched template (`COPILOT_DATA_SOURCE=replay`, all creds empty), so `replay`/no-creds is correct behaviour, not a loader bug. Added `scripts/check_env.py` (safe, no secret values) + `dotenv_path`/`dotenv_loaded` in `/api/status` to make this self-evident. **To go live on the work laptop:** run `python scripts/check_env.py`, then in `.env` set `COPILOT_DATA_SOURCE=datadog`, a `DATADOG_ACCESS_TOKEN` (or API+APP key), `DATADOG_TENANT_TAG`, `DATADOG_DISCOVERY_METRIC`, `DATADOG_SITE`, and restart. Still blocks live-validation of Iteration 2 until done on the laptop.
- **Datadog scope-discovery query/response shape (needs live validation).** `list_scopes` enumerates tag values by issuing `<discovery_metric>{scope} by {env|tenant}` and reading each series' `tag_set`. Unverified against a real org: (a) is `tag_set` the right field, (b) is `DATADOG_DISCOVERY_METRIC` (default `system.cpu.user`) a metric that actually carries `env`/tenant tags in your org, (c) does the `{(env:a OR env:b) AND tenant:x}` scope syntax behave as intended? Tune once `.env` works.
- **What tag key is your "tenant"?** `DATADOG_TENANT_TAG` defaults to `tenant`; set it to your org's actual key (e.g. `customer`/`account`) when validating live.
- **Events multi-select filtering (known limitation).** The events API `tags` param ANDs its entries, so we only tag-filter a dimension when exactly one value is selected; multi-select env/tenant falls back to the time window for events. Revisit if events need precise multi-value scoping.
- **Which real Datadog signals matter most** for your environment (specific metrics, monitors, services)? Needed to make the LiveDatadogAdapter useful on *your* prod. Can default to common golden-signal metrics until specified.
- **Canonical demo incident realism** — is the generic deployment-induced latency story fine, or should the replay mimic a real past incident from your org?

## Resolved
- Run target → local, but able to connect to real production Datadog. (DECISIONS 2026-06-26)
- LLM access → Anthropic key available, cost-conscious mode. (DECISIONS 2026-06-26)
- UI → chat-style, backend as hero. (DECISIONS 2026-06-26)
- Secret handling → gitignored `.env`, never committed. (DECISIONS 2026-06-26)
