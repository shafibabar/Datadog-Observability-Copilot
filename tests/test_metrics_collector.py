"""Spec for the metrics collector (metrics/collector.py).

The collector is run by a Claude Code `Stop` hook after each response. It:
  - parses the session transcript into prompt cycles (real tokens/timestamps),
  - classifies intent (file mutation => implementation),
  - computes git deltas attributable to *this turn* (committed since last snapshot
    + current working tree − last snapshot), including untracked new files,
  - appends one JSONL record, deduped by prompt timestamp.

Pure logic is unit-tested; the git arithmetic is integration-tested against a
real temporary git repo. Stdlib only — the hook runs without the venv.
"""
import json
import os
import subprocess

import pytest

from metrics import collector as C


# ---------- transcript parsing ----------

def _user(ts, text):
    return json.dumps({"timestamp": ts, "message": {"role": "user", "content": text}})


def _assistant(ts, text, tools=None, usage=None):
    content = [{"type": "text", "text": text}]
    for t in (tools or []):
        content.append({"type": "tool_use", "name": t, "input": {}})
    msg = {"role": "assistant", "content": content}
    if usage:
        msg["usage"] = usage
    return json.dumps({"timestamp": ts, "message": msg})


def _tool_result(ts):
    return json.dumps({"timestamp": ts, "message": {
        "role": "user", "content": [{"type": "tool_result", "content": "ok"}]}})


def test_parse_cycles_extracts_tokens_intent_and_summary():
    lines = [
        _user("2026-06-27T10:00:00Z", "Why is checkout slow?"),
        _assistant("2026-06-27T10:00:30Z", "Investigating…", tools=["Read"],
                   usage={"input_tokens": 100, "output_tokens": 50,
                          "cache_read_input_tokens": 9, "cache_creation_input_tokens": 3}),
        _tool_result("2026-06-27T10:00:31Z"),
        _assistant("2026-06-27T10:01:00Z", "Here is the answer.",
                   usage={"input_tokens": 200, "output_tokens": 80,
                          "cache_read_input_tokens": 1, "cache_creation_input_tokens": 0}),
        _user("2026-06-27T10:05:00Z", "Now wire it up"),
        _assistant("2026-06-27T10:06:00Z", "Done.", tools=["Edit", "Bash"],
                   usage={"input_tokens": 10, "output_tokens": 5,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}),
    ]
    cycles = C.parse_cycles(lines)
    assert len(cycles) == 2

    c0 = cycles[0]
    assert c0["prompt_ts"] == "2026-06-27T10:00:00Z"
    assert c0["response_ts"] == "2026-06-27T10:01:00Z"   # last assistant msg in cycle
    assert c0["summary"].startswith("Why is checkout slow")
    assert c0["tokens"]["input"] == 300 and c0["tokens"]["output"] == 130
    assert c0["tokens"]["cache_read"] == 10
    assert c0["mutated"] is False                          # only Read

    c1 = cycles[1]
    assert c1["mutated"] is True                           # Edit present


def test_parse_cycles_ignores_tool_results_and_meta():
    lines = [
        json.dumps({"timestamp": "t", "isMeta": True,
                    "message": {"role": "user", "content": "system note"}}),
        _tool_result("t2"),
        _user("2026-06-27T10:00:00Z", "real question"),
        _assistant("2026-06-27T10:00:05Z", "answer", usage={"input_tokens": 1, "output_tokens": 1}),
    ]
    cycles = C.parse_cycles(lines)
    assert len(cycles) == 1
    assert cycles[0]["summary"] == "real question"


def test_classify_intent():
    assert C.classify_intent(True) == "implementation"
    assert C.classify_intent(False) == "planning_qa"


def test_summarize_truncates_and_singlelines():
    s = C.summarize("  hello\n  world  " + "x" * 200)
    assert "\n" not in s and len(s) <= C.SUMMARY_MAX


# ---------- git output parsing & arithmetic ----------

def test_parse_numstat():
    text = "10\t2\tapp/x.py\n5\t0\ttests/test_x.py\n-\t-\tassets/logo.png\n"
    dm = C.parse_numstat(text)
    assert dm["app/x.py"] == {"added": 10, "removed": 2}
    assert dm["tests/test_x.py"]["added"] == 5
    assert "assets/logo.png" not in dm   # binary (-) skipped


def test_parse_name_status():
    text = "A\tnew.py\nM\told.py\nD\tgone.py\n"
    st = C.parse_name_status(text)
    assert st == {"new.py": "A", "old.py": "M", "gone.py": "D"}


def test_subtract_diffmaps_isolates_this_turn():
    total = {"a.py": {"added": 30, "removed": 5}, "b.py": {"added": 10, "removed": 0}}
    baseline = {"a.py": {"added": 20, "removed": 2}}     # already counted last turn
    this_turn = C.subtract_diffmaps(total, baseline)
    assert this_turn["a.py"] == {"added": 10, "removed": 3}
    assert this_turn["b.py"] == {"added": 10, "removed": 0}


def test_subtract_drops_zero_and_negative_noise():
    total = {"a.py": {"added": 20, "removed": 2}}
    baseline = {"a.py": {"added": 20, "removed": 2}}     # unchanged since last turn
    assert C.subtract_diffmaps(total, baseline) == {}


def test_count_new_tests():
    diff = (
        "+++ b/tests/test_x.py\n"
        "+def test_one():\n+    assert True\n"
        "+    async def test_two():\n"
        "-def test_removed():\n"
    )
    assert C.count_new_tests(diff) == 2


# ---------- records: indexing, dedupe, shape ----------

def test_next_index():
    assert C.next_index([]) == 1
    assert C.next_index([{"index": 3}, {"index": 7}, {"index": 5}]) == 8


def test_already_recorded():
    recs = [{"prompt_ts": "2026-06-27T10:00:00Z"}]
    assert C.already_recorded(recs, "2026-06-27T10:00:00Z") is True
    assert C.already_recorded(recs, "2026-06-27T11:00:00Z") is False


def test_build_record_planning_has_no_implementation_block():
    cyc = {"prompt_ts": "a", "response_ts": "b", "summary": "hi",
           "tokens": {"input": 1, "output": 2, "cache_read": 0, "cache_creation": 0, "total": 3},
           "mutated": False}
    rec = C.build_record(cyc, index=5, session_id="s", git_stats=None)
    assert rec["index"] == 5 and rec["intent"] == "planning_qa"
    assert rec["kind"] == "user_prompt"
    assert "implementation" not in rec
    assert rec["source"] == "live"


def test_build_record_implementation_includes_git_stats():
    cyc = {"prompt_ts": "a", "response_ts": "b", "summary": "build",
           "tokens": {"input": 1, "output": 2, "cache_read": 0, "cache_creation": 0, "total": 3},
           "mutated": True}
    gs = {"lines_added": 12, "lines_removed": 3, "lines_updated_est": 3,
          "files_created": 1, "files_modified": 2, "files_deleted": 0,
          "tests_added": 4, "docs_context_updated": ["STATE.md"], "dependencies_installed": 0}
    rec = C.build_record(cyc, index=1, session_id="s", git_stats=gs)
    assert rec["intent"] == "implementation"
    assert rec["implementation"]["files_created"] == 1
    assert rec["implementation"]["tests_added"] == 4
    assert rec["implementation"]["docs_context_updated"] == ["STATE.md"]


# ---------- git integration (real temp repo) ----------

def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(str(r), "init", "-q")
    _git(str(r), "config", "user.email", "t@t.com")
    _git(str(r), "config", "user.name", "t")
    (r / "seed.txt").write_text("hello\n")
    _git(str(r), "add", "-A")
    _git(str(r), "commit", "-qm", "seed")
    return str(r)


def test_git_turn_stats_detects_created_modified_and_untracked(repo):
    head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    baseline = {"head": head, "worktree": {}}

    # modify a tracked file + create a new (untracked) file with tests
    with open(os.path.join(repo, "seed.txt"), "a") as f:
        f.write("more\n")
    os.makedirs(os.path.join(repo, "docs", "context"), exist_ok=True)
    with open(os.path.join(repo, "tests_new.py"), "w") as f:
        f.write("def test_a():\n    assert 1\n")
    with open(os.path.join(repo, "docs", "context", "STATE.md"), "w") as f:
        f.write("state\n")

    stats, new_baseline = C.git_turn_stats(repo, baseline)
    assert stats["lines_added"] >= 3            # +more, test file, state file
    assert stats["files_created"] == 2          # tests_new.py, docs/context/STATE.md
    assert stats["files_modified"] == 1         # seed.txt
    assert stats["tests_added"] == 1
    assert "STATE.md" in stats["docs_context_updated"]
    assert new_baseline["head"] == head


def test_git_turn_stats_only_counts_new_work_since_baseline(repo):
    head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    # First turn: add 2 lines to a new file.
    with open(os.path.join(repo, "work.py"), "w") as f:
        f.write("a = 1\nb = 2\n")
    stats1, base1 = C.git_turn_stats(repo, {"head": head, "worktree": {}})
    assert stats1["lines_added"] == 2

    # Second turn (no commit between): add 1 more line. Only the new line counts.
    with open(os.path.join(repo, "work.py"), "a") as f:
        f.write("c = 3\n")
    stats2, _ = C.git_turn_stats(repo, base1)
    assert stats2["lines_added"] == 1


# ---------- end-to-end collect ----------

def test_collect_appends_one_record_and_dedupes(repo, tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join([
        _user("2026-06-27T10:00:00Z", "wire the endpoint"),
        _assistant("2026-06-27T10:01:00Z", "done", tools=["Write"],
                   usage={"input_tokens": 10, "output_tokens": 20,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}),
    ]) + "\n")
    with open(os.path.join(repo, "feature.py"), "w") as f:
        f.write("x = 1\n")

    jsonl = tmp_path / "prompts.jsonl"
    state = tmp_path / "state.json"
    rec = C.collect(str(transcript), repo, str(jsonl), str(state), session_id="s")
    assert rec is not None and rec["intent"] == "implementation"
    assert rec["implementation"]["files_created"] == 1
    assert len(jsonl.read_text().strip().splitlines()) == 1

    # Running again on the same transcript must not duplicate the cycle.
    again = C.collect(str(transcript), repo, str(jsonl), str(state), session_id="s")
    assert again is None
    assert len(jsonl.read_text().strip().splitlines()) == 1
