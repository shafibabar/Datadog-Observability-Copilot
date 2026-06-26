# TESTING.md — TDD discipline & metrics log

## Protocol (binding)
- **Regression invariant:** once a test is green it stays green. Every step runs the full suite (`pytest`); previously-passing tests must never break.
- **Test-first:** for each new capability, write the failing spec tests first (red), then implement to green. (The Iteration 0 *foundation* tests were retrofitted — noted honestly below — everything from the reasoning engine onward is genuinely test-first.)
- **Honest metric:** each step reports `passing / total (%)`. If the pass % drops *because new red spec tests were added for a new requirement*, that is stated explicitly — it is expected TDD behavior, not regression.
- **Pending tests** (spec written ahead of implementation) are marked `@pytest.mark.pending` so red-by-design specs are mechanically distinct from real breakage.

## How to run
```
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                 # full suite
pytest -q              # quiet
pytest tests/test_config.py::test_defaults_when_unset   # a single test
pytest --cov=app       # with coverage (currently 99%)
```

## Metrics log (newest first)
| Date | Step | Passing | Total | Pass % | Notes |
|---|---|---|---|---|---|
| 2026-06-26 | Iteration 1: conversations + memory + UI | 113 | 113 | 100% | Test-first: +15 net specs. Engine conversational memory (history fed to prompt, optional + bounded); store messages/conversations (roundtrip, isolation, title, recency ordering, activity bump); section serializer (typed + JSON-safe); conversation-aware Copilot (isolation, memory, titling, persist turns, rerender-no-LLM, artifact, JSON-safe); conversation API (create/list/get/chat/artifact, 404/400/503). `test_copilot.py` and `test_app.py` rewritten for the new API. Frontend boot + response-shape smoke-tested (not unit-tested). Coverage **99%**. Zero regressions. |
| 2026-06-26 | Refactor + hardening pass | 98 | 98 | 100% | Refactor (behavior-preserving, existing tests guarded it): `rank` ordering moved onto `Confidence`/`Severity` enums (removed dup rank-maps in artifacts); shared `outstanding_questions()` helper (de-duped between sections + artifacts); type-safe `EventSource.SUPPORT` compare. +16 specs closing real gaps: enum `rank` ordering, `workspace_db` config, `reasoning_objects(snapshot_seq=)` filter, confidence-history isolates distinct hypotheses, **security guard (no secret bytes in workspace DB)**, artifact empty-investigation degradation, `build_default_session`/`_build_source` production factory (replay/datadog/fallback/keyless), `extract_json` malformed branch, engine rejects non-object JSON, `/api/artifact` 503-without-session, lazy session build+cache. **Coverage 99%** (main/copilot/engine 100%). Zero regressions. |
| 2026-06-26 | Incident Summary artifact | 82 | 82 | 100% | Test-first: +11 specs (registry contains incident_summary, unknown key raises KeyError, audience + core sections present, picks highest-confidence hypothesis (not the LOW one), severity derived from timeline, grounded transform (summary + recommendation verbatim), to_markdown title/headings; CopilotSession.artifact serializes from latest snapshot with NO llm call + investigates-if-empty; `/api/artifact` generates summary + rejects unknown key with 400). LLM faked. Zero regressions. |
| 2026-06-26 | Chat endpoint wired | 71 | 71 | 100% | Test-first: +14 specs (persona registry has the 5 charter personas, persona=config-lens, get_persona default-to-sre, render grounded in investigation, render differs by persona on same facts, leadership more concise than sre, pm surfaces customer-impact+recommendation; CopilotSession creates workspace + records snapshot, second ask appends history, reply ships evidence, persona-switch re-renders with NO llm call, rerender-without-prior runs one; app `/api/chat` investigates when session wired + empty-message re-render). LLM faked, ReplayAdapter, in-memory store — no key/network. Zero regressions. |
| 2026-06-26 | Investigation Workspace | 57 | 57 | 100% | Test-first: +14 specs (create/get workspace, append-only snapshots w/ incrementing seq, history preserved, latest, full Investigation roundtrip, persistence across store instances, queryable reasoning atoms, confidence-over-time per hypothesis, hypothesis-key normalisation, registry covers 11 charter sections, ordered+titled render, section population, affected-services derivation). SQLite; no LLM/network/keys. Zero regressions. |
| 2026-06-26 | Reasoning engine | 43 | 43 | 100% | Test-first: +12 specs (reasoning models, timeline, evidence catalog/grounding, JSON extraction, Anthropic wrapper via injected fake, engine assembly + invalid-evidence filtering). Claude fully mocked — no key/spend. Zero regressions. |
| 2026-06-26 | LiveDatadogAdapter | 32 | 32 | 100% | Test-first: +8 specs (auth headers, query params, metric/event parsing, severity + source mapping, empty series, time window). All HTTP mocked via httpx.MockTransport — no keys/network. Zero regressions. |
| 2026-06-26 | DataSource + ReplayAdapter | 24 | 24 | 100% | Test-first: +13 specs (telemetry model, DataSource interface, replay canonical incident) written red, then implemented to green. Zero regressions. |
| 2026-06-26 | Foundation test baseline | 11 | 11 | 100% | Retrofitted tests for config (secret-free, capability flags, defaults) + app surface (healthz, status, index, chat). No pending tests yet. Env fix: pinned wheels for Python 3.14; dropped Jinja2 (page is static). |
