# STATE.md — live status

_Last updated: 2026-08-05_

## Current gate
Plan + Design **approved**. **Iterations 0–2 COMPLETE.** Three workstreams have landed: **Iteration 3 (platform-narrowed scope + `@` scope menu)**, the **monitors/correlation layer** (Terraform-extracted EC metrics, wired Stage-2 guard classifier), and **namespace-scoped metrics** (2026-08-05, below). All code-complete and green — see their sections below and DECISIONS for the full narrative. **Combined pending items before going live:**
1. **DONE — live Datadog validated on the work laptop (2026-08-05).** The verified working config is in item 2 below. Note `DATADOG_TENANT_TAG=tenant` (NOT `kube_namespace` — that's the environment tag).
2. **DONE — the live Datadog demo works end to end (2026-08-05).** Verified against the real org: 420-metric registry from discovery, 8 metric series with real data per question, a real LLM investigation citing 45 evidence entries, `/api/scopes` serving 2 environments + 10 tenants, timeline bounded to 60. Working config: `COPILOT_DATA_SOURCE=datadog`, `DATADOG_METRIC_NAMESPACES=ec.*`, **`DATADOG_ENV_TAG=kube_namespace`**, **`DATADOG_TENANT_TAG=tenant`**, `DATADOG_CA_BUNDLE=<pem>`, `COPILOT_PLATFORM_DEFAULT_WINDOW_DAYS=7`. See the third-pass section below.
3. ~~**BLOCKER — no `ec.*` metric has yielded a datapoint yet.**~~ RESOLVED — it was the 4h window; these metrics are sparse (36–153 points per 7 days). Metric-name discovery is CONFIRMED (16,117 names / 1,297 `ec.*`; 420 base + 877 generated sub-metrics; 14 services); events flow at ~1000/hour.
4. **Manually verify the `@` scope menu in a real browser** — this sandbox couldn't install Chromium's system deps (needs root `apt`), so the caret-anchored popover/chip behavior is covered only by static contract tests, not an actual render.

## Session 2026-08-05 — namespace-scoped metrics (345 passing, 1 skipped)
- **Problem (user-reported):** `DATADOG_DISCOVERY_METRIC=system.cpu.user` was being used to enumerate tenants but doesn't carry the wanted tags; and there was **no way to say "only `ec.*` metrics are in scope"** — the registry came solely from a hardcoded `ec\.` regex over the Terraform repo (~320 metrics), with the four `system.*` infra defaults never filtered out. The target demo config is ~500 `ec.*` metrics + ~10 explicitly-listed tenants, with nothing else filled in.
- **Answer to "does this already work?":** tenants **already did** (a `COPILOT_PLATFORM_TENANTS` list short-circuits `Copilot.list_scopes`, so the discovery metric is never queried for them); metric scope did **not** exist at all.
- **Built (TDD, +46 specs):**
  - **`app/telemetry/namespaces.py`** (new, pure/stdlib `fnmatch`): `parse_patterns` (`"ec.*, ea.*"`; bare `ec`/`ec.` → `ec.*`), `matches` (case-insensitive; **empty patterns match everything** so unset config is unchanged), `prefixes` (literal heads, feeds the Terraform regex), `filter_queries(registry, patterns, keep=…)`.
  - **`DATADOG_METRIC_NAMESPACES`** replaces **`DATADOG_DISCOVERY_METRIC`** (removed). In `/api/status` as `metric_namespaces`.
  - **Live metric-name discovery** (`datadog.discover_metric_names`): namespace-filtered, sorted, **best-effort — any failure yields `[]`** rather than breaking startup. Discovered names get a generic `avg:<name>{*}`.
  - **Merge** (`copilot.merged_metric_queries`): precedence **configured > extracted > discovered**, then namespace-filtered with configured names as a deliberate escape hatch. Returns `{}` (not `None`) when namespaces are set, so an empty in-scope registry can **never** silently fall back to `system.*`.
  - **Terraform extraction** parameterized by namespace prefixes (`build_monitors_index(path, namespaces=…)`), including module-alias prefix stripping.
  - **Guard vocabulary** now also derives from the in-scope registry via `index.service_vocabulary` ("ec.quota_manager.x" → "quota manager") — real service questions pass the guard with **no** `COPILOT_PLATFORM_METRICS` hand-listing.
  - **Tag discovery** groups the first in-scope registry metric by the tag; an empty registry makes **no** HTTP call.
  - **UI:** the `@` root menu hides Environment/Tenant when that list is empty (Duration always shows) — listing only tenants is now a clean config, not a dead-end submenu.
  - **Diagnostics:** `check_env.py` reports namespaces + the offline Terraform-extracted count; `datadog_probe.py` gained the metrics-list probe (counts returned/in-scope names **and the namespaces that actually exist in the org**).
- **Test hermeticity fix:** `_clear()` in **both** `tests/test_copilot.py` and `tests/test_config.py` now unsets `DATADOG_METRIC_NAMESPACES`/`DATADOG_METRIC_QUERIES`/`MONITORS_REPO_PATH`/`DATADOG_TENANT_TAG` — the demo laptop's real `.env` has these set and a populated `.env` **did** break `test_config.py` once the value was filled in. Verified green both with a clean env and with laptop-like vars exported.

### Second pass, same day — registry quality (360 passing, 1 skipped)
First live probe results drove two approved follow-ups (see DECISIONS 2026-08-05 later):
- **CONFIRMED live:** `GET /api/v1/metrics?from=<epoch>` → 200, `{"metrics":[…]}`, 16,117 names, **1,297 matching `ec.*`**. `/api/v1/validate` 403s with a PAT (expected). `/api/v1/events` returns all mapped fields at ~1000/hour.
- **Generated sub-metrics excluded** (`namespaces.is_stat_submetric`): `.count/.sum/.min/.max/.avg/.median/.NNpercentile` are Datadog artifacts of one distribution — 1,297 in-scope names is roughly ~500 distinct signals. Dropped inside `filter_queries`; explicitly-configured names bypass.
- **Extracted metrics must be confirmed reporting:** the probe's Terraform sample metric returned **0 series and 0 tags** (in the `.tf` files, not emitting). `merged_metric_queries` now intersects extracted with discovered whenever discovery returned anything; if discovery returns nothing the full extracted set survives (graceful degradation intact).
- **Probe restructured** to discover first and target a confirmed-live metric, with a registry-analysis block (base vs sub-metric counts, services, Terraform confirmed-vs-missing). The old ordering made 4 of 7 steps silently inconclusive.
- **Real numbers from the org:** 1,297 in-scope names = **420 base metrics + 877 generated sub-metrics** across **14 services** (alerting_service, centralised_audit, config_curator, echo_engine, indexer, lookback_service, manual_run_service, pipeline_qualifier, quota_manager, reporting, review_service, surveillance_filter, …) — the ~500-vs-1,297 gap is explained. Of 320 Terraform-extracted metrics, **183 are in the live list and 137 are not** (43% dead), which vindicates the confirmed-reporting rule.
- **Probe steps 8–10 added** after the second run still returned zero datapoints: a 7-day × 3-aggregation survey across up to 8 metrics, a tag-key survey that only runs against a metric with data, and a base-vs-sub-metric comparison that would expose the sub-metric filter as wrong if only the siblings hold data. Verified against a fake Datadog (`httpx.MockTransport`) including the failure scenario they're meant to detect.

### Third pass, same day — live demo actually working (377 passing, 1 skipped, 98% cov)
The third probe run returned data, and turning that into a working live demo exposed four more real defects:
- **Sparse metrics** — 36–153 points per metric over **7 days**, zero over 4 hours. `COPILOT_PLATFORM_DEFAULT_WINDOW_DAYS=7` is required, not cosmetic.
- **`DATADOG_ENV_TAG` (new config).** This org carries **no `env` tag at all** (`by {env}` → the single placeholder series `env:N/A`); environment is `kube_namespace` (`ep-perflab-uat`, `ep-smarsh-staging`) and the real tenant tag is **`tenant`** (`conductperf`, `msanity`, `sanity2`, …). `env` was hardcoded in 4 places in the adapter, so every environment filter would have matched nothing. **This corrects the earlier note that EC's tenant is `kube_namespace` — it is not; `kube_namespace` is the environment.** `N/A` is now filtered out of discovered tag values.
- **Resolver was keyed off the Terraform index, not the live registry.** With `MONITORS_REPO_PATH` unset, discovery yields 420 metrics while the Terraform index is empty — `select_metrics` bailed on `if not index.metric_queries`, returning zero metrics, and the engine then passed `metrics=None` meaning **query all 420** (one HTTP call each). Now `available` (the source registry) is the authority, alias vocabulary is derived from metric names via `index.aliases_from_metric_names` when Terraform is absent, and the engine bounds whenever the registry exceeds `DEFAULT_TOP_K` *or* a Terraform index exists.
- **Timeline was unbounded** — the events API returns ~1000/hour, so the workspace's "Timeline of Events" section shipped 1000 rows per reply. `build_timeline` now bounds to `MAX_TIMELINE_EVENTS=60`, keeping critical/warning events ahead of routine noise and staying chronological.
- **Silent TLS degradation (noted, not fixed):** with `DATADOG_CA_BUNDLE` unset, discovery's blanket `except` turned a `CERTIFICATE_VERIFY_FAILED` into an empty registry with no visible reason. Worth surfacing the failure reason in `/api/status`.

Grounded in **TDD** (see `TESTING.md`, `BUILD-LOG.md` for the narrative).

## Iteration 3 — platform-narrowed scope (done 2026-07-27)
- **Problem:** scope selection (env/tenant) was a hard, unconditional gate before any question could be asked; separately, the relevance guard only recognized ~40 generic words, so most real phrasing about a specific tenant/service/metric was refused (Stage-2 classifier was unwired at the time — since fixed, see the correlation-layer session below).
- **Phase 1 (backend):** new optional `COPILOT_PLATFORM_ENVIRONMENTS/_TENANTS/_METRICS/_LOG_SOURCES/_TRACE_SERVICES/_DEFAULT_WINDOW_DAYS` config (`.env.example`, `app/config.py`, README table of exactly where to find each value in the Datadog UI). `Scope.validation_error()` no longer requires a selection or duration. `Copilot._with_defaults()` backfills missing scope fields from that config (or an unfiltered 2-day window if unconfigured) and persists the result — zero scope interaction needed to ask a question. `guard.evaluate()` gained `extra_vocabulary` (the platform's own terms), combined in `build_copilot` with the wired Stage-2 classifier (belt-and-suspenders: deterministic vocabulary first, semantic classifier for the remaining ambiguous middle). `list_scopes()`/`/api/scopes` serve the static config directly, bypassing live discovery. `scripts/check_env.py` reports what resolved.
- **Phase 2 (UI):** removed the old scope-picker panel entirely. Composer (`#input`) rebuilt as `contenteditable` (a plain `<textarea>` can't host an inline chip). Typing `@` opens a caret-anchored `#at-menu` (Environment/Tenant/Duration); a selection inserts a locked, non-editable chip (click-to-remove "✕", never backspace-parsed). `composerText()`/`scopePayload()` read the message and the scope as two independent passes over the composer's DOM — never one parsed from the other — and an empty selection (`scopePayload()` returns `undefined`) reuses the conversation's existing scope rather than resetting it every turn. Persona stays a plain visible `<select>`. Send is no longer gated on scope.
- See DECISIONS 2026-07-27 for both phases, including the untested-in-a-real-browser caveat.
- **Next:** manual/real-browser verification of the `@` menu; fill in real `COPILOT_PLATFORM_*` values on the company laptop.

## Session 2026-07-13 (later) — correlation layer (278 passing, 1 skipped)
- **Approved via AskUserQuestion, built A→D test-first (+14 specs, `tests/test_correlation.py`):**
  - **A. Extraction** (`app/monitors/index.py`): all `modules/*/*.tf` (monitors + dashboards) scanned for `ec.*` timeseries queries → normalized query map (**320** on the real repo; interpolations/thresholds/grouping stripped, scope reset to `{*}`, `.as_count()/.as_rate()` kept) + **36-alias vocabulary** (module names + metric service segments).
  - **B. Adapter merge** (`copilot.merged_metric_queries`): extracted queries feed `LiveDatadogAdapter`; precedence `DATADOG_METRIC_QUERIES` > extracted > infra defaults.
  - **C. Resolver** (`app/monitors/resolver.py`): deterministic top-8 selection (alias phrases in question > recent history at reduced weight > metric-name token overlap; golden-set fallback = one throughput + one error metric per service). `build_evidence_catalog(metrics=…)` bounds queries; replay path unchanged.
  - **D. Prompt surface**: service vocabulary added to the always-injected monitors context; selected metrics arrive as normal evidence entries.
- **Smoke vs real repo:** "how many messages are being processed per second" → `ec.quota_manager.pipeline_processed_counter`; "message processing health" → the message-processing dashboard's own metrics. Discovery: EC's tenant == `kube_namespace` (existing `DATADOG_TENANT_TAG` seam covers it — config only).

## Session 2026-07-13 — monitors integration + debt cleanup (264 passing, 1 skipped)
- **Monitors knowledge base** (`app/monitors/`): indexes the `ec-conduct-dd-monitors` Terraform repo (21 monitors, 11 dashboards on the primary machine) via **`MONITORS_REPO_PATH`** (new config; empty → empty index, graceful; `monitors_repo_configured` in `/api/status`). Context injected into **every** reasoning prompt when non-empty. Tests use a fixture Terraform tree (portable). Docs: `docs/MONITORS_INTEGRATION.md`.
- **Guard Stage-2 classifier is now WIRED** (`app/guard_classifier.py`, hooked up in `build_copilot`; supersedes the 2026-07-08 "intentionally left unwired" note). Fail-**closed** on classifier errors per the guard's contract. Stage-1 keyword list expanded with EC service + queue vocabulary, then **re-tightened** (generic words like `rate`/`count`/`issue`/`problem` removed — Stage 2 owns the ambiguous middle).
- **`app/reasoning/domain.py`**: method knowledge (metric categories, failure modes, investigation steps) in the system prompt; fictional tenants/services removed. Also fixed: null-tolerant Datadog event mapping (`31a2377`).
- **User-reported gap (drives the current gate):** answers still don't correlate user terms with the Terraform-captured system because the extracted `ec.*` metrics never reach the Datadog adapter's queries — the evidence catalog has no EC telemetry. Correlation-layer proposal pending approval.

## Iteration 2 — done (2026-07-08)
- **Relevance & abuse guard** (`app/guard.py`) — finished a red-ahead spec left in the tree; pre-reasoning gate wired into `Copilot.ask`; `_SYSTEM` hardened. Committed `b0e9316`.
- **Scoped investigations backend** — `Scope{env, tenant, window}` (≤7 days) persisted per conversation, overridable per turn, threaded engine→evidence→DataSource. Datadog `{(env..) AND tenant:..}` filters + `list_scopes` discovery (env→tenant narrowing, configurable `DATADOG_TENANT_TAG`/`DATADOG_DISCOVERY_METRIC`); Replay ignores scope. Store `scope_json`+migration+`delete_workspace`; Copilot summary-derived subjects + rename/delete; API scope-validation (`400`), `/api/scopes`, `PATCH`/`DELETE`. Committed `d08e726`.
- **UI** — Claude.ai warm light theme; **pure-CSS flex layout** (renders with no JS — replaced a fragile JS-set grid that broke twice on stale cache); mtime-versioned CSS/JS + `no-store` so caches can't go stale. Scope controls are ONE **drill-down scope menu** under the prompt (`#scope-trigger` → Environment / Tenant / Duration / Explain-as submenus; multi-select checkmarks + filter for env/tenant; presets + custom-range **modal** for Duration; personas w/ descriptions). Sidebar rename/delete (⋯). Resizable/collapsible panels (persisted). Per-reply copy.
- **.env diagnostics** — `scripts/check_env.py` (safe) + `dotenv_path`/`dotenv_loaded` in `/api/status`.
- **Tests** — declarative UI-contract tests (`tests/test_web_ui.py`) + opt-in Playwright browser smoke (`tests/test_smoke_playwright.py`, skips without a browser).

## Tests
**377 passing, 1 skipped (Playwright, needs a browser), 98% coverage.** No pending (red) specs. The +78 over the previous 299 came from the 2026-08-05 namespace-scope session (new `tests/test_namespaces.py`, plus namespace/discovery/UI specs added to the datadog, correlation, copilot, config and web-ui suites). The 299 baseline was Iteration 3 (platform-scope config + guard vocabulary + relaxed Scope validation, then the `@`-menu composer rewrite) merged with the monitors/correlation-layer branch (Terraform-extracted metrics, wired Stage-2 guard classifier) — both landed cleanly with only two textual merge conflicts (`app/copilot.py`'s `build_copilot` wiring, and this file + `DECISIONS.md`), no semantic clashes. Full per-step log in `TESTING.md`.

## Known gap (deferred)
"`.env` not loading" was **diagnosed (2026-07-08)** as a config-*contents* issue, not a loader bug: the repo `.env` is the untouched template (`data_source=replay`, creds empty), which is why `/api/status` shows defaults. Added `scripts/check_env.py` (safe diagnostic) + `dotenv_path`/`dotenv_loaded` in `/api/status`. To go live on the laptop: run the diagnostic, set `COPILOT_DATA_SOURCE=datadog` + a Datadog credential + `DATADOG_TENANT_TAG` + `DATADOG_METRIC_NAMESPACES`, restart. Still blocks live scope-discovery validation until done on the laptop.

## Scope/UI feature — decisions (2026-07-08)
- **Scope model** = `{environments[], tenants[], start, end}`, persisted per conversation, overridable per message, threaded into the DataSource query filter + window.
- **Tenant** is not a native Datadog concept → configurable tag key `DATADOG_TENANT_TAG` (default `tenant`); `env` is the standard environment tag.
- **Duration**: presets + custom, **max 7-day span, end ≤ now**, enforced client- and server-side (token discipline).
- **Conversation subject**: derived from the investigation summary (no extra LLM call).
- **`⧉` header icon removed**; right panel gets a collapse chevron; per-response copy buttons added.
- **Guard Stage-2 classifier** intentionally left unwired (classifier=None → hybrid refuses the ambiguous middle, conservative-safe). Wiring a cheap LLM classifier is a roadmap item.

## Latest session — done (2026-07-03)
- **Fixed: dashboard tabs didn't switch.** They were JS-driven and only tab *presence* was tested, not switching — a broken switch shipped (stale cached JS in the browser). Reworked to a **pure-CSS radio hack** (`:checked ~ #tab-view`): switching now works with no JS; JS only re-renders the visible tab's canvases. +3 tests assert the switch declaratively (two radios, one default-checked; radios-before-views order; the CSS reveal rules). Lesson logged: don't mark UI behavior "manual-smoke-only" — make it declarative + testable.
- **Collector now records passing-test count.** Bug: the collector never set `tests_run/passing/failing`, so every auto-collected impl turn wrote `0` (the dashboard's `113` peak was only from reconstructed history). Fixed with `count_tests(repo)` — a stdlib-only static count of defined `test_…` functions under `tests/` — recorded as `tests_run == tests_passing` (green invariant ⇒ defined == passing). No pytest run in the hook (venv/latency/red-mid-edit reasons). The next auto-collected impl turn records the current total (168 now).
- **Metrics dashboard, two tabs.** Added a second **Timeline** tab: the same metric families rolled up **by calendar day** (from `prompt_ts`) — prompts/tokens/lines/files per day, cumulative tests-passing + cumulative cost over dates, and a per-prompt log table with exact timestamps. Tab 1 (**Overview**) is unchanged. Analytics gained `date`/`prompt_ts` on each row + `by_day` + `timeline_summary` (tolerant: no-timestamp records bucket to `"unknown"`, excluded from the span). Frontend: tabbed HTML/CSS + `renderTimeline()`; `charts.js` untouched. Verified over real HTTP (both tabs + `/api/metrics` timeline keys). See DECISIONS 2026-07-03 (Timeline tab).
- **Ongoing metrics logging confirmed:** the `Stop` hook + `collector.py` keeps appending one record per turn (data now at 27 prompts, `source: live` today).

## Earlier this session — done (2026-07-03)
- **No API key needed.** `ClaudeCliClient` (`app/reasoning/llm.py`) shells out to the local `claude` CLI headless (`claude -p …`), reusing the Claude Code login. `COPILOT_LLM_BACKEND` (`auto`/`cli`/`sdk`) selects the backend; `auto` = CLI when keyless, else SDK. `build_copilot(settings, cli_available=…)` reworked; returns None only when there's no key **and** no CLI. Subprocess runner + CLI detection injected → suite stays offline.
- **Datadog PAT.** `DATADOG_ACCESS_TOKEN` → `Authorization: Bearer`; preferred over the legacy `DD-API-KEY`/`DD-APPLICATION-KEY` pair (kept as fallback). `has_datadog` true with a token alone.
- **Docs.** README rewritten (Connect-Claude section w/ obtain steps for CLI + API key; Datadog PAT obtain steps; **metrics dashboard run section**). `.env.example`, `CLAUDE.md`, `DECISIONS.md` updated. See DECISIONS 2026-07-03.

## Done
- Plan + Design approved (stack, dependencies, roadmap shape, context-file layout, key-handling constraint).
- `CLAUDE.md` written (guidance for future Claude sessions).
- Iteration 0 **foundation scaffold**:
  - `.gitignore` (secrets/`.env`/db excluded), `.env.example` (empty template), `requirements.txt`.
  - `app/config.py` — secure runtime secret loading (single seam; secret-free `status()`).
  - `app/main.py` — FastAPI app: `/healthz`, `/api/status`, `/` chat page, `/api/chat` (placeholder).
  - Chat UI: `app/web/templates/index.html`, `static/styles.css`, `static/app.js` (persona selector, status banner).
  - `docs/context/` files created.
- **TDD setup + foundation test baseline**: `pytest.ini`, `requirements-dev.txt`, `tests/test_config.py`, `tests/test_app.py`. 11/11 green. Verified by Claude in a clean venv.

## In progress
- **Metrics subsystem shipped** (separate from the product, in `metrics/`). Run the dashboard: `python -m uvicorn metrics.dashboard:app --port 8055` → http://127.0.0.1:8055. The `Stop` hook in `.claude/settings.json` auto-appends a record after each prompt (loaded — confirmed firing).
- Deferred app work (pre-metrics): persist per-message evidence for reload; the Claude **CLI LLM backend** (`ClaudeCliClient` behind the `LLMClient` seam — planned/approved, not built); more artifacts.

## Metrics subsystem — done this session (2026-06-27)
- `metrics/prompts.jsonl` (JSONL data) + `SCHEMA.md`; historical baseline reconstructed from transcripts (real tokens/timestamps) + git + TESTING.md.
- `metrics/collector.py` (stdlib-only) run by a `Stop` hook → appends one record per prompt cycle; per-turn git delta arithmetic; dedupe.
- `metrics/analytics.py` tolerant loader + aggregations (robust to schema evolution / malformed lines).
- `metrics/dashboard.py` (FastAPI) + `metrics/static/` (dependency-free canvas charts) → live local dashboard on a free port.

## Iteration 1 — done this session
- **Conversational memory:** `ReasoningEngine.investigate(question, history=...)` feeds bounded recent turns into the prompt (`history_limit`, default 6). Follow-ups now carry context.
- **Multiple conversations:** a conversation = one Workspace + its messages, all persisted. Store gained a `messages` table, `title`/`updated_at` on workspaces, and `add_message`/`get_messages`/`list_conversations`/`set_title`. Activity bumps recency.
- **Conversation-aware service:** `CopilotSession` → **`Copilot`** (`app/copilot.py`): `new_conversation`, `list_conversations`, `get_conversation`, `ask` (persists turns + memory), `rerender` (no LLM), `artifact`. Factory renamed `build_default_session` → **`build_copilot`**.
- **Section serializer:** `serialize_sections()` (type-dispatched) → JSON for the live panel.
- **API:** `/api/conversations` (GET list, POST create), `/api/conversations/{id}` (GET), `/{id}/chat`, `/{id}/artifact`. 404 on unknown conversation, 400 on unknown artifact, 503 keyless.
- **New 3-pane UI:** conversation sidebar (list/new/switch, last-opened persisted in localStorage) · restyled chat with markdown + per-reply evidence disclosure · collapsible **live Investigation Workspace panel** rendering serialized sections with confidence/severity color vocabulary. Boot + shape smoke-tested.

## Next (Iteration 0 remainder) — all test-first from here
1. ~~`DataSource` interface + ReplayAdapter (canonical incident)~~ ✅ done.
2. ~~LiveDatadogAdapter (read-only)~~ ✅ done (HTTP mocked in tests).
3. ~~Claude reasoning engine~~ ✅ done (structured objects, timeline, evidence grounding; Claude mocked in tests).
4. ~~Investigation Workspace (SQLite, append-with-history) + core sections~~ ✅ done (`app/workspace/`: store + registry-driven sections; confidence-over-time; 14 specs).
5. ~~Wire `/api/chat` to workspace + reasoning; persona-rendered answers; "show me the evidence"~~ ✅ done (`app/copilot.py` CopilotSession; `app/personas.py` registry+render; evidence ships per reply; UI persona-switch re-renders without re-reasoning; 14 specs).
6. ~~One artifact: Incident Summary~~ ✅ done (`app/artifacts.py`: registry-driven transform; `/api/artifact`; UI button; 11 specs).
7. ~~Run instructions in README~~ ✅ done (full non-dev copy-paste guide + demo walkthrough; boot verified via smoke test).

**→ Iteration 0 definition of done MET.** Next gate: agree Iteration 1 scope (candidates in ROADMAP "Later iterations").

## Needed from human
- Tests run keyless (LLM faked). To run the app **live** locally you now need **either** a Claude Code CLI sign-in (`claude`, no key — default) **or** an `ANTHROPIC_API_KEY` in `.env`; chat degrades gracefully with neither. Datadog only if `COPILOT_DATA_SOURCE=datadog` — a `DATADOG_ACCESS_TOKEN` (PAT) or the legacy API+App key pair.
