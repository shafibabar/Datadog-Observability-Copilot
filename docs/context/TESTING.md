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
pytest --cov=app       # with coverage
```

## Metrics log (newest first)
| Date | Step | Passing | Total | Pass % | Notes |
|---|---|---|---|---|---|
| 2026-06-26 | Incident Summary artifact | 82 | 82 | 100% | Test-first: +11 specs (registry contains incident_summary, unknown key raises KeyError, audience + core sections present, picks highest-confidence hypothesis (not the LOW one), severity derived from timeline, grounded transform (summary + recommendation verbatim), to_markdown title/headings; CopilotSession.artifact serializes from latest snapshot with NO llm call + investigates-if-empty; `/api/artifact` generates summary + rejects unknown key with 400). LLM faked. Zero regressions. |
| 2026-06-26 | Chat endpoint wired | 71 | 71 | 100% | Test-first: +14 specs (persona registry has the 5 charter personas, persona=config-lens, get_persona default-to-sre, render grounded in investigation, render differs by persona on same facts, leadership more concise than sre, pm surfaces customer-impact+recommendation; CopilotSession creates workspace + records snapshot, second ask appends history, reply ships evidence, persona-switch re-renders with NO llm call, rerender-without-prior runs one; app `/api/chat` investigates when session wired + empty-message re-render). LLM faked, ReplayAdapter, in-memory store — no key/network. Zero regressions. |
| 2026-06-26 | Investigation Workspace | 57 | 57 | 100% | Test-first: +14 specs (create/get workspace, append-only snapshots w/ incrementing seq, history preserved, latest, full Investigation roundtrip, persistence across store instances, queryable reasoning atoms, confidence-over-time per hypothesis, hypothesis-key normalisation, registry covers 11 charter sections, ordered+titled render, section population, affected-services derivation). SQLite; no LLM/network/keys. Zero regressions. |
| 2026-06-26 | Reasoning engine | 43 | 43 | 100% | Test-first: +12 specs (reasoning models, timeline, evidence catalog/grounding, JSON extraction, Anthropic wrapper via injected fake, engine assembly + invalid-evidence filtering). Claude fully mocked — no key/spend. Zero regressions. |
| 2026-06-26 | LiveDatadogAdapter | 32 | 32 | 100% | Test-first: +8 specs (auth headers, query params, metric/event parsing, severity + source mapping, empty series, time window). All HTTP mocked via httpx.MockTransport — no keys/network. Zero regressions. |
| 2026-06-26 | DataSource + ReplayAdapter | 24 | 24 | 100% | Test-first: +13 specs (telemetry model, DataSource interface, replay canonical incident) written red, then implemented to green. Zero regressions. |
| 2026-06-26 | Foundation test baseline | 11 | 11 | 100% | Retrofitted tests for config (secret-free, capability flags, defaults) + app surface (healthz, status, index, chat). No pending tests yet. Env fix: pinned wheels for Python 3.14; dropped Jinja2 (page is static). |
