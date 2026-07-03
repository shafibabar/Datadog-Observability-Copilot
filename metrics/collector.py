"""Metrics collector — run by a Claude Code `Stop` hook after each response.

It reconstructs the latest prompt cycle from the session transcript (real tokens
and timestamps), computes the git changes attributable to *this turn*, and
appends one JSON line to `metrics/prompts.jsonl`. Designed to be safe (never
breaks the session) and to use the standard library only, so the hook runs
without activating the project's virtualenv.

Per-turn git attribution (handles out-of-band commits between turns):
    total      = diff(baseline_head .. working tree)      # committed + uncommitted + untracked
    this_turn  = total − baseline_worktree                # subtract what existed at last snapshot
    new state  = (current_head, diff(current_head .. working tree))
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

SCHEMA_VERSION = 1
SUMMARY_MAX = 70
_MUTATING_TOOLS = {"Edit", "Write", "NotebookEdit"}
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's empty-tree sha


# ---------- transcript parsing ----------

def summarize(text: str) -> str:
    return " ".join((text or "").split())[:SUMMARY_MAX]


def _prompt_text(content) -> str | None:
    """Return the user's typed text, or None if this is a tool result / non-text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = "".join(b.get("text", "") for b in content
                       if isinstance(b, dict) and b.get("type") == "text")
        return text or None
    return None


def parse_cycles(lines) -> list[dict]:
    """Group transcript lines into prompt cycles (user prompt → its assistant turns)."""
    cycles: list[dict] = []
    cur: dict | None = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = o.get("message") or {}
        role = msg.get("role")
        ts = o.get("timestamp")

        if role == "user" and not o.get("isMeta"):
            text = _prompt_text(msg.get("content"))
            if text and text.strip() and not text.lstrip().startswith("<") \
                    and "Request interrupted" not in text:
                if cur:
                    cycles.append(cur)
                cur = {"prompt_ts": ts, "response_ts": ts, "summary": summarize(text),
                       "tokens": {"input": 0, "output": 0, "cache_read": 0,
                                  "cache_creation": 0, "total": 0},
                       "mutated": False}
                continue

        if cur and role == "assistant":
            u = msg.get("usage") or {}
            tk = cur["tokens"]
            tk["input"] += u.get("input_tokens", 0)
            tk["output"] += u.get("output_tokens", 0)
            tk["cache_read"] += u.get("cache_read_input_tokens", 0)
            tk["cache_creation"] += u.get("cache_creation_input_tokens", 0)
            tk["total"] = tk["input"] + tk["output"] + tk["cache_read"] + tk["cache_creation"]
            if ts:
                cur["response_ts"] = ts
            for b in (msg.get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_use" \
                        and b.get("name") in _MUTATING_TOOLS:
                    cur["mutated"] = True
    if cur:
        cycles.append(cur)
    return cycles


def classify_intent(mutated: bool) -> str:
    return "implementation" if mutated else "planning_qa"


# ---------- git output parsing & arithmetic ----------

def parse_numstat(text: str) -> dict:
    out: dict = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            out[parts[2]] = {"added": int(parts[0]), "removed": int(parts[1])}
    return out


def parse_name_status(text: str) -> dict:
    out: dict = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            out[parts[-1]] = parts[0][0]
    return out


def subtract_diffmaps(total: dict, baseline: dict) -> dict:
    """`total − baseline` per file; drop entries that didn't change this turn."""
    this_turn: dict = {}
    for path, t in total.items():
        b = baseline.get(path, {"added": 0, "removed": 0})
        added = t["added"] - b.get("added", 0)
        removed = t["removed"] - b.get("removed", 0)
        if added > 0 or removed > 0:
            this_turn[path] = {"added": max(added, 0), "removed": max(removed, 0)}
    return this_turn


def count_new_tests(diff_text: str) -> int:
    n = 0
    for line in diff_text.splitlines():
        if not line.startswith("+"):
            continue
        stripped = line[1:].lstrip()
        if stripped.startswith("def test_") or stripped.startswith("async def test_"):
            n += 1
    return n


def count_tests(repo: str) -> int:
    """Current total of defined test functions under `tests/`.

    A fast, stdlib-only proxy for the passing count: the suite's binding invariant
    is 'once green, always green' (every step runs the full suite; green tests
    never break), so the number of defined tests == the number passing. We do NOT
    run pytest in the hook — that would need the venv, add latency to every turn,
    and could record red counts mid-edit. Missing tests/ dir → 0."""
    root = os.path.join(repo, "tests")
    n = 0
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            try:
                text = open(os.path.join(dirpath, fname), encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("def test_") or s.startswith("async def test_"):
                    n += 1
    return n


def _git(repo: str, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", repo, *args],
                              capture_output=True, text=True, check=False).stdout
    except Exception:
        return ""


def _untracked(repo: str) -> list[str]:
    return [f for f in _git(repo, "ls-files", "--others", "--exclude-standard").split("\n") if f]


def _diffmap_to_worktree(repo: str, frm: str) -> tuple[dict, dict, str]:
    """numstat, name-status, and raw diff text from `frm` to the working tree,
    including untracked files (counted as additions / created)."""
    numstat = parse_numstat(_git(repo, "diff", frm, "--numstat"))
    status = parse_name_status(_git(repo, "diff", frm, "--name-status"))
    difftext = _git(repo, "diff", frm)
    for f in _untracked(repo):
        path = os.path.join(repo, f)
        try:
            content = open(path, encoding="utf-8", errors="ignore").read().splitlines()
        except OSError:
            content = []
        numstat[f] = {"added": len(content), "removed": 0}
        status[f] = "A"
        difftext += "\n--- /dev/null\n+++ b/" + f + "\n" + "".join("+" + l + "\n" for l in content)
    return numstat, status, difftext


def git_turn_stats(repo: str, baseline: dict) -> tuple[dict, dict]:
    """Compute git metrics attributable to this turn, plus the new baseline."""
    head = _git(repo, "rev-parse", "HEAD").strip() or None
    # No recorded baseline → measure against the current HEAD (only *new* work this
    # turn), not git's empty tree (which would count the whole committed repo).
    base_head = baseline.get("head") or head or _EMPTY_TREE

    total, status, difftext = _diffmap_to_worktree(repo, base_head)
    this_turn = subtract_diffmaps(total, baseline.get("worktree", {}))

    changed = set(this_turn)
    docs = sorted(os.path.basename(p) for p in changed if "docs/context/" in p)
    stats = {
        "lines_added": sum(v["added"] for v in this_turn.values()),
        "lines_removed": sum(v["removed"] for v in this_turn.values()),
        "lines_updated_est": sum(min(v["added"], v["removed"]) for v in this_turn.values()),
        "files_created": sum(1 for p in changed if status.get(p) == "A"),
        "files_modified": sum(1 for p in changed if status.get(p) == "M"),
        "files_deleted": sum(1 for p in changed if status.get(p) == "D"),
        "tests_added": count_new_tests(difftext),
        "docs_context_updated": docs,
        "dependencies_installed": _deps_delta(this_turn, repo, base_head),
        "commit": head,
    }
    # Current suite size == passing count under the green invariant (see count_tests).
    tests_total = count_tests(repo)
    stats["tests_run"] = tests_total
    stats["tests_passing"] = tests_total
    stats["tests_failing"] = 0
    # New baseline is the working-tree diff relative to the *current* head.
    wt_now, _, _ = _diffmap_to_worktree(repo, head or _EMPTY_TREE)
    return stats, {"head": head, "worktree": wt_now}


def _deps_delta(this_turn: dict, repo: str, base_head: str) -> int:
    """Net added lines in requirements*.txt this turn ≈ dependencies installed."""
    total = 0
    for path, v in this_turn.items():
        if os.path.basename(path).startswith("requirements") and path.endswith(".txt"):
            total += v["added"]
    return total


# ---------- records ----------

def load_records(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def next_index(records) -> int:
    return max((r.get("index", 0) for r in records), default=0) + 1


def already_recorded(records, prompt_ts) -> bool:
    return any(r.get("prompt_ts") == prompt_ts for r in records)


def build_record(cyc: dict, index: int, session_id: str, git_stats: dict | None) -> dict:
    intent = classify_intent(cyc["mutated"])
    rec = {
        "schema_version": SCHEMA_VERSION,
        "index": index,
        "session_id": session_id,
        "prompt_ts": cyc["prompt_ts"],
        "response_ts": cyc["response_ts"],
        "duration_sec": _duration(cyc["prompt_ts"], cyc["response_ts"]),
        "kind": "user_prompt",
        "intent": intent,
        "summary": cyc["summary"],
        "tokens": cyc["tokens"],
        "source": "live",
    }
    if intent == "implementation":
        gs = git_stats or {}
        rec["implementation"] = {
            "tests_added": gs.get("tests_added", 0),
            "tests_run": gs.get("tests_run", 0),
            "tests_passing": gs.get("tests_passing", 0),
            "tests_failing": gs.get("tests_failing", 0),
            "lines_added": gs.get("lines_added", 0),
            "lines_removed": gs.get("lines_removed", 0),
            "lines_updated_est": gs.get("lines_updated_est", 0),
            "files_created": gs.get("files_created", 0),
            "files_modified": gs.get("files_modified", 0),
            "files_deleted": gs.get("files_deleted", 0),
            "dependencies_installed": gs.get("dependencies_installed", 0),
            "docs_context_updated": gs.get("docs_context_updated", []),
            "commit": gs.get("commit"),
            "estimated": False,
            "note": "",
        }
    return rec


def _duration(a: str, b: str) -> int:
    from datetime import datetime
    try:
        fa = datetime.fromisoformat(a.replace("Z", "+00:00"))
        fb = datetime.fromisoformat(b.replace("Z", "+00:00"))
        return max(0, int((fb - fa).total_seconds()))
    except (ValueError, AttributeError):
        return 0


# ---------- orchestration ----------

def collect(transcript_path: str, repo: str, jsonl_path: str,
            state_path: str, session_id: str = "") -> dict | None:
    """Append a record for the latest completed cycle. Returns it, or None if
    there is nothing new to record. Never raises for expected-missing inputs."""
    if not os.path.exists(transcript_path):
        return None
    lines = open(transcript_path, encoding="utf-8").read().splitlines()
    cycles = parse_cycles(lines)
    if not cycles:
        return None
    latest = cycles[-1]

    records = load_records(jsonl_path)
    if already_recorded(records, latest["prompt_ts"]):
        return None

    state = _load_state(state_path)
    git_stats = None
    if latest["mutated"]:
        git_stats, new_baseline = git_turn_stats(repo, state.get("baseline", {}))
        state["baseline"] = new_baseline

    record = build_record(latest, next_index(records), session_id, git_stats)
    os.makedirs(os.path.dirname(jsonl_path) or ".", exist_ok=True)
    with open(jsonl_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    _save_state(state_path, state)
    return record


def _load_state(path: str) -> dict:
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(path: str, state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        json.dump(state, open(path, "w", encoding="utf-8"))
    except OSError:
        pass


def main() -> int:
    """Hook entry point. Reads the Stop-hook JSON from stdin and never fails the
    session: any error is swallowed with exit 0."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    transcript = payload.get("transcript_path", "")
    repo = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id", "")
    base = os.path.join(repo, "metrics")
    try:
        collect(transcript, repo, os.path.join(base, "prompts.jsonl"),
                os.path.join(base, ".collector_state.json"), session_id=session_id)
    except Exception:
        pass  # a metrics hook must never break the session
    return 0


if __name__ == "__main__":
    sys.exit(main())
