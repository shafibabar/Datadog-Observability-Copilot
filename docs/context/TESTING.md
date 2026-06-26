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
| 2026-06-26 | Foundation test baseline | 11 | 11 | 100% | Retrofitted tests for config (secret-free, capability flags, defaults) + app surface (healthz, status, index, chat). No pending tests yet. Env fix: pinned wheels for Python 3.14; dropped Jinja2 (page is static). |
