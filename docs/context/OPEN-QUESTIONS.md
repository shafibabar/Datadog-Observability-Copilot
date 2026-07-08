# OPEN-QUESTIONS.md

Unresolved items awaiting human input. Resolve → move the decision to `DECISIONS.md`.

## Open
- **`.env` not loading at runtime (BLOCKER for live scope).** On the work laptop with real Datadog creds, `curl /api/status` returns defaults (`data_source=replay`, no creds), so `load_dotenv` isn't picking up the file. Build + tests are unaffected (HTTP mocked), but live env/tenant discovery and scoped queries can't be exercised until this is fixed. Likely causes to check: `.env` location vs. the uvicorn working directory, file name/format, or a real env var shadowing it. Deferred by the user; must resolve before live-validating Iteration 2.
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
