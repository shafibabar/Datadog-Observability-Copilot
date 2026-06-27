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
| `tests_run` / `tests_passing` / `tests_failing` | int | From the pytest run (red→green). |
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
- **Historical entries** (`source: reconstructed`) are rebuilt from transcripts
  (tokens/timestamps — exact) + git (lines/files — exact) + `TESTING.md` (test
  counts). Where a commit bundled several prompts, `implementation.estimated` is
  `true` (e.g., the Workspace work landed in the chat-wiring commit).
