"""Pre-commit guard: a change under tests/ must come with a TESTING.md entry.

`docs/context/TESTING.md` is the project's per-step TDD log, and `STATE.md` cites
it as the full per-step record. On 2026-08-05 three passes' worth of test changes
(299 -> 377 tests) were committed without a single entry — the docs closest to the
code got updated, the one furthest from it was forgotten, and only the human
noticing caught it. A hook is the right fix because the failure mode is
forgetfulness, not disagreement.

Run by `.githooks/pre-commit`. Also runnable by hand:

    python3 scripts/check_testing_log.py

Stdlib only and no imports from `app/`, so it works with no venv active — a hook
that needs an activated venv is a hook that silently stops running.
"""
from __future__ import annotations

import subprocess
import sys

#: The one file that satisfies the guard (an exact repo-relative path — another
#: file merely *named* TESTING.md is not the per-step log).
TESTING_LOG = "docs/context/TESTING.md"

#: Everything under here is a test change. Trailing slash matters: it keeps
#: "contests/foo.py" and "app/latest/x.py" from matching.
TESTS_DIR = "tests/"


def missing_log_entry(staged_paths) -> bool:
    """True when the staged set changes tests but not the TDD log.

    Pure and git-free so it is directly testable; the caller supplies the paths.
    """
    paths = [p.strip() for p in staged_paths if p and p.strip()]
    touches_tests = any(p.startswith(TESTS_DIR) for p in paths)
    return touches_tests and TESTING_LOG not in paths


def staged_paths() -> list[str]:
    """Repo-relative paths staged for commit (adds, edits and deletions alike)."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True, text=True, check=True,
    ).stdout
    return out.splitlines()


_MESSAGE = f"""
pre-commit: tests changed but {TESTING_LOG} did not.

{TESTING_LOG} is the per-step TDD log that STATE.md points at as the full record.
Add a row for this step — date, what was specced and why, passing/total, coverage
— then stage it:

    git add {TESTING_LOG}

Staged test files:
{{files}}

If this change genuinely needs no log entry (a rename, a typo, a fixture tweak
mid-step), skip the guard:

    git commit --no-verify
"""


def main() -> int:
    paths = staged_paths()
    if not missing_log_entry(paths):
        return 0
    listed = "\n".join(f"  {p}" for p in paths if p.startswith(TESTS_DIR))
    print(_MESSAGE.format(files=listed), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
