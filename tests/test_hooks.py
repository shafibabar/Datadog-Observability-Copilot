"""Spec for the pre-commit guard that keeps the TDD log honest.

TESTING.md is this project's per-step TDD record, and STATE.md points at it as
"the full per-step log". On 2026-08-05 three sessions' worth of test changes
(299 -> 377) landed without a single entry, and the omission was only caught
because the human asked. This guard makes that mechanically impossible.

The check is pure and git-free so it can be tested; the hook only supplies the
staged file list. Stdlib only — the hook must work with no venv active.
"""
from scripts.check_testing_log import TESTING_LOG, missing_log_entry

# --- the violation the guard exists to catch --------------------------------


def test_changing_tests_without_the_log_is_a_violation():
    assert missing_log_entry(["tests/test_datadog.py"])


def test_changing_tests_with_the_log_is_fine():
    assert not missing_log_entry(["tests/test_datadog.py", TESTING_LOG])


def test_adding_a_new_test_file_also_requires_a_log_entry():
    assert missing_log_entry(["tests/test_namespaces.py", "app/telemetry/namespaces.py"])


def test_deleting_a_test_file_also_requires_a_log_entry():
    # A deletion shows up in the staged list the same way an edit does, and losing
    # coverage is exactly the kind of change the log should explain.
    assert missing_log_entry(["tests/test_obsolete.py"])


# --- things that must NOT trip it ------------------------------------------


def test_app_only_changes_are_fine():
    assert not missing_log_entry(["app/copilot.py", "README.md"])


def test_an_empty_commit_is_fine():
    assert not missing_log_entry([])


def test_touching_only_the_log_is_fine():
    assert not missing_log_entry([TESTING_LOG])


def test_a_differently_located_testing_md_does_not_satisfy_the_guard():
    # Only the real per-step log counts — not some other file of the same name.
    assert missing_log_entry(["tests/test_x.py", "docs/TESTING.md"])


def test_a_path_merely_containing_tests_is_not_a_test_change():
    # "app/latest/..." and "contests/..." must not be mistaken for the tests tree.
    assert not missing_log_entry(["app/latest/thing.py", "contests/foo.py"])


def test_the_metrics_subsystems_own_tests_still_count():
    # Anything under tests/ counts, regardless of which subsystem it covers.
    assert missing_log_entry(["tests/test_metrics_collector.py"])


def test_blank_and_whitespace_paths_are_ignored():
    # `git diff --cached --name-only` output ends with a newline.
    assert not missing_log_entry(["", "  "])
    assert missing_log_entry(["tests/test_x.py", ""])
