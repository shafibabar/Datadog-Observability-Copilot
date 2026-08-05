# Monitors Integration: Observability Copilot ↔ ec-conduct-dd-monitors

The Copilot indexes the **ec-conduct-dd-monitors** Terraform repo (Datadog
monitors + dashboards for the EC Conduct support team) so questions about
alerting configuration are understood and answered with real configuration
knowledge, and so investigations know which signals the org actually watches.

## Configuration

Set the local checkout path in `.env` (machine-specific; empty disables the
index — the app degrades gracefully to an empty index, never crashes):

```bash
MONITORS_REPO_PATH=/path/to/ec-conduct-dd-monitors
```

`/api/status` reports `monitors_repo_configured` so a missing path is visible
without reading logs.

## How it works

0. **Metric scope** (`DATADOG_METRIC_NAMESPACES`, e.g. `ec.*` or `ec.*, ea.*`):
   which metric namespaces the scan looks for. Passed as
   `build_monitors_index(path, namespaces=…)`; unset defaults to `ec.` — the
   original behavior. See `app/telemetry/namespaces.py`.
1. **Index build** (`app/monitors/index.py`, at `build_copilot` time):
   - Scans `modules/*/main.tf` for `datadog_monitor` resources → monitor name,
     resource id, first in-scope metric name in its query, alert-channel refs.
   - Scans **every** `modules/*/*.tf` (monitor AND dashboard modules) for in-scope
     timeseries queries → a normalized metric-query map (~320 `ec.*` on the real
     repo: eval-window prefixes, thresholds, and `by {...}` grouping stripped; scope
     reset to `{*}` so the adapter's Scope rewriting applies; `.as_count()/.as_rate()`
     preserved) plus a vocabulary **alias map** (~36 aliases: module names like
     `ec_message_processing_summary_dashboard` → "message processing", metric
     service segments → "quota manager", …).
   - Scans the root `main.tf` for `var.dashboards.<name>` references → dashboard
     names.
2. **Adapter merge** (`app/copilot.py::merged_metric_queries`): the extracted
   query map feeds `LiveDatadogAdapter`'s metric registry, alongside metrics
   discovered live from Datadog under the same namespaces. Precedence: explicit
   `DATADOG_METRIC_QUERIES` > extracted > live-discovered, then narrowed to the
   namespaces. Extraction beats discovery because it carries the real aggregation
   (`sum:` … `.as_count()`) instead of a generic `avg:`. With namespaces set, the
   built-in infra defaults (`system.*`) are never used.

   **But extraction is not trusted for existence.** The `.tf` files can reference
   metrics that no longer emit — verified live 2026-08-05, when
   `ec.centralised_audit.communication_event_dlt_counter` returned 0 series on a
   bare `{*}` query and 0 tags. So whenever live discovery returns anything, an
   extracted metric must also appear in the live list to enter the registry;
   otherwise the resolver could select it and the investigation would cite no
   telemetry. If discovery returns nothing (failed / not configured), the full
   extracted set is used — degrade, don't empty. Datadog's generated statistical
   sub-metrics (`.count/.sum/.min/.max/…`) are dropped here too.
3. **Relevance resolver** (`app/monitors/resolver.py`): per question, selects
   the top-K (8) metrics via alias-phrase matches (recent history counts at
   reduced weight for follow-ups) + metric-name token overlap; with no signal,
   a golden set (one throughput + one error metric per service). Deterministic —
   no LLM call. The evidence catalog (`build_evidence_catalog(metrics=…)`)
   queries only that selection, so a 320-metric registry never means 320 HTTP
   calls or a token blowup.
4. **Context injection** (`app/reasoning/engine.py`): the monitors list + the
   service vocabulary go into **every** reasoning prompt when non-empty (not
   keyword-gated); selected metrics arrive as real evidence entries.
5. **Guard** (`app/guard.py`): EC service names and monitoring vocabulary are in
   the Stage-1 fast-allow list, **extended automatically with the service phrases
   implied by the in-scope registry** (`index.service_vocabulary`:
   `ec.quota_manager.x` → "quota manager"); the ambiguous middle goes to the
   Stage-2 LLM classifier (`app/guard_classifier.py`), which fails closed per the
   guard's contract.

Note: in this org "tenant" is the Kubernetes namespace — set
`DATADOG_TENANT_TAG=kube_namespace` so Scope selections translate correctly.

## Testing

`tests/test_monitors.py` and `tests/test_correlation.py` exercise the index,
resolver, evidence bounding, and merge precedence against fixture Terraform
trees in `tmp_path` — the suite never depends on a real local checkout, so it
is green on any machine.

## Known limitations / next steps

- The index is built once at startup (not refreshed when the Terraform repo
  changes).
- Alert thresholds/messages are not yet extracted.
- Resolver selection is deterministic token/alias matching; LLM-assisted
  selection is a deliberate non-goal for now.
- Live validation against the real Datadog org is pending (needs the work
  laptop's `.env`).
