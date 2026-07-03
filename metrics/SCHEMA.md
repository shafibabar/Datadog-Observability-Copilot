# Vibe-Coding Metrics — schema & design

This subsystem tracks and audits our AI-assisted ("vibe coding") sessions. It is
**separate from the product** (`app/`) and has three layers:

1. **Data** — `metrics/prompts.jsonl` (this schema). One JSON object per line, one
   line per prompt cycle, append-only.
2. **Collection** — `metrics/collector.py`, run automatically by a Claude Code
   `Stop` hook after each response (reads the session transcript for real tokens
   + git for diffs). *(built in step 3)*
3. **Analytics** — `metrics/dashboard.py` (FastAPI) + `metrics/static/` (Chart.js),
   live local graphs over the JSONL. *(built in steps 4–5)*

## Running the dashboard

```
source .venv/bin/activate
python -m uvicorn metrics.dashboard:app --port 8055
```
Then open <http://127.0.0.1:8055>. The page polls `/api/metrics` every 5s ("live"
toggle in the header). Graphs are drawn by a small dependency-free canvas module
(`static/charts.js`) — no Chart.js / CDN, fully offline. Free, local, no paid lib.

### Two tabs
- **Overview** — per-prompt view keyed by prompt `index` (tokens, tests, lines, files, cost, intent split, docs-per-file).
- **Timeline** — the same metric families rolled up by **calendar day** (derived from `prompt_ts`): prompts/tokens/lines/files per day, cumulative tests-passing and cumulative cost over dates, plus a **prompt-log table with exact timestamps**. The active tab renders on each poll (a hidden canvas can't measure its width).

## `/api/metrics` output shape
`analytics.aggregate()` returns `summary`, `prompts` (per-prompt rows; each now also
carries `prompt_ts` and a derived `date`), `intent_split`, `kind_split`, `docs_context`,
and — for the Timeline tab:
- `by_day`: ordered list, one dict per calendar date (ascending; an `"unknown"` bucket for
  records with no valid timestamp sorts last). Each: `prompts`, `planning_qa`,
  `implementation`, `input_tokens`, `output_tokens`, `total_tokens`, `cost_usd` +
  `cumulative_cost_usd`, `tests_added`, `peak_tests_passing` + `cumulative_peak_tests`,
  `lines_added`/`lines_removed`, `files_created`/`files_modified`/`files_deleted`,
  `docs_updates`, `duration_sec`.
- `timeline_summary`: `first_date`, `last_date`, `active_days`, `busiest_day`
  (`{date, prompts}` or `null`). The `"unknown"` bucket is excluded from the span.

All of this stays tolerant to schema drift and bad data — a record with a missing or
malformed `prompt_ts` lands in the `"unknown"` bucket instead of breaking the rollup.

## Why JSONL
Append-only (no rewrite / merge conflicts), clean git diffs (one new line per
prompt), tolerant to parse, and naturally streamable to the dashboard. Each
record carries `schema_version` so the dashboard stays robust as fields evolve.

## Record schema (one line in `prompts.jsonl`)

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | Schema version (currently `1`). |
| `index` | int | Sequential prompt-cycle number. |
| `session_id` | str | Claude Code transcript/session id. |
| `prompt_ts` | ISO-8601 | Timestamp of the user's prompt (from transcript). |
| `response_ts` | ISO-8601 | Timestamp of Claude's completed response. |
| `duration_sec` | int | `response_ts − prompt_ts`. |
| `kind` | enum | `user_prompt` (real intent) or `tool_confirmation` (a Y/N authorization). |
| `intent` | enum | `planning_qa` (discussion/reads) or `implementation` (file mutations). |
| `summary` | str | Short label from the prompt text. |
| `tokens` | object | `{input, output, cache_read, cache_creation, total}` — real, from transcript usage. |
| `source` | enum | `reconstructed` (historical) or `live` (auto-collected). |
| `implementation` | object\|absent | Present only when `intent == implementation` (below). |

### `implementation` sub-object

| Field | Type | Meaning |
|---|---|---|
| `tests_added` | int | New `def test_…` functions in the diff. |
| `tests_run` / `tests_passing` / `tests_failing` | int | Current suite size, from a static count of defined `test_…` functions under `tests/` (`failing` = 0). Under the "once green, always green" invariant, defined == passing. The hook does **not** run pytest (would need the venv + add latency); historical `reconstructed` rows used the real `TESTING.md` pytest counts. |
| `lines_added` / `lines_removed` | int | Exact, from `git diff --numstat`. |
| `lines_updated_est` | int | **Estimate** = `min(added, removed)`; git has no native "updated". |
| `files_created` / `files_modified` / `files_deleted` | int | From `git diff --name-status` (A/M/D). |
| `dependencies_installed` | int | New packages added to `requirements*.txt`. |
| `docs_context_updated` | [str] | `docs/context/*` files touched in this cycle. |
| `commit` | str\|null | Linked git commit, if any. |
| `estimated` | bool | `true` when attribution to this prompt is approximate. |
| `note` | str | Human note on what the cycle delivered. |

## Definitions / honest limitations
- **intent** is classified as `implementation` when the turn contains a file
  mutation tool (`Edit`/`Write`/`NotebookEdit`); pure reads / bash inspection /
  pytest count as `planning_qa`. (Adjustable.)
- **`tool_confirmation` cycles** (Y/N permission prompts) are only partially
  observable; historical entries are all `user_prompt`. Forward capture is
  best-effort via the hook.
- **Token caches**: `cache_read` is large because every tool-using turn re-reads
  cached context; treat `input + output` as the "fresh" volume and cache fields
  as context-reuse. All values are real (from transcript `usage`).
- **`tests_passing` for live turns** is a **static count of defined test functions**
  under `tests/`, not a live pytest run — chosen so the Stop hook stays stdlib-only,
  fast, and can't record a red mid-edit count. The green invariant makes defined ==
  passing. (Earlier live records pre-dating this fix show `0`; the peak line uses the
  cumulative max, so it isn't dragged down by them.)
- **Historical entries** (`source: reconstructed`) are rebuilt from transcripts
  (tokens/timestamps — exact) + git (lines/files — exact) + `TESTING.md` (test
  counts). Where a commit bundled several prompts, `implementation.estimated` is
  `true` (e.g., the Workspace work landed in the chat-wiring commit).
