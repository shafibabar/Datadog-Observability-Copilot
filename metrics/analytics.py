"""Dashboard data layer: tolerant loading + pure aggregations over prompts.jsonl.

Robustness is the design goal — data written by any future prompt (new fields, a
bumped schema_version, even a half-written/malformed line) must never break the
dashboard. The loader skips bad lines; `normalize` defaults every field it reads;
unknown fields are ignored. All aggregation is pure (list[dict] -> dict) and unit
tested.
"""
from __future__ import annotations

import json

# Approximate USD per 1M tokens (Claude Sonnet-class public rates) — the records
# don't store the model, so cost is an ESTIMATE for trend/scale, not billing.
_RATE_PER_M = {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_creation": 3.75}


def load_records(path: str) -> list[dict]:
    """Read JSONL, skipping blank and malformed lines. Missing file -> []."""
    out: list[dict] = []
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return out
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def normalize(rec: dict) -> dict:
    """Coerce a raw record into a known shape with safe defaults. Tolerant to
    missing/unknown fields and future schema versions."""
    tk = rec.get("tokens") or {}
    tokens = {
        "input": _int(tk.get("input")),
        "output": _int(tk.get("output")),
        "cache_read": _int(tk.get("cache_read")),
        "cache_creation": _int(tk.get("cache_creation")),
    }
    tokens["total"] = _int(tk.get("total")) or sum(tokens.values())

    intent = rec.get("intent", "planning_qa")
    if intent not in ("planning_qa", "implementation"):
        intent = "planning_qa"

    impl = None
    raw_impl = rec.get("implementation")
    if isinstance(raw_impl, dict):
        impl = {
            "tests_added": _int(raw_impl.get("tests_added")),
            "tests_passing": _int(raw_impl.get("tests_passing")),
            "lines_added": _int(raw_impl.get("lines_added")),
            "lines_removed": _int(raw_impl.get("lines_removed")),
            "files_created": _int(raw_impl.get("files_created")),
            "files_modified": _int(raw_impl.get("files_modified")),
            "files_deleted": _int(raw_impl.get("files_deleted")),
            "dependencies_installed": _int(raw_impl.get("dependencies_installed")),
            "docs_context_updated": [str(x) for x in (raw_impl.get("docs_context_updated") or [])],
        }

    return {
        "index": _int(rec.get("index")),
        "intent": intent,
        "kind": rec.get("kind", "user_prompt") or "user_prompt",
        "summary": rec.get("summary", "") or "",
        "duration_sec": _int(rec.get("duration_sec")),
        "prompt_ts": rec.get("prompt_ts"),
        "tokens": tokens,
        "implementation": impl,
    }


def estimate_cost(tokens: dict) -> float:
    return round(sum(_int(tokens.get(k)) * rate / 1_000_000
                     for k, rate in _RATE_PER_M.items()), 4)


def aggregate(records: list[dict]) -> dict:
    """Compute everything the dashboard renders, from raw records."""
    rows = sorted((normalize(r) for r in records), key=lambda r: r["index"])

    prompts = []
    cum_output = cum_total = 0
    cum_docs = 0
    docs_per_file: dict[str, int] = {}
    docs_over_time = []

    summary = {
        "total_prompts": 0, "total_input_tokens": 0, "total_output_tokens": 0,
        "total_tokens": 0, "total_tests_added": 0, "peak_tests_passing": 0,
        "total_lines_added": 0, "total_lines_removed": 0,
        "total_files_created": 0, "total_files_modified": 0, "total_files_deleted": 0,
        "total_dependencies_installed": 0, "estimated_cost_usd": 0.0,
        "intent_split": {"planning_qa": 0, "implementation": 0},
        "kind_split": {},
    }
    intent_split = {"planning_qa": 0, "implementation": 0}
    kind_split: dict[str, int] = {}

    for r in rows:
        tk = r["tokens"]
        cum_output += tk["output"]
        cum_total += tk["total"]
        cost = estimate_cost(tk)
        impl = r["implementation"]

        row = {
            "index": r["index"], "intent": r["intent"], "kind": r["kind"],
            "summary": r["summary"], "duration_sec": r["duration_sec"],
            "input": tk["input"], "output": tk["output"],
            "cache_read": tk["cache_read"], "cache_creation": tk["cache_creation"],
            "total": tk["total"], "cumulative_output": cum_output,
            "cumulative_total": cum_total, "cost_usd": cost,
            "tests_passing": impl["tests_passing"] if impl else None,
            "tests_added": impl["tests_added"] if impl else 0,
            "lines_added": impl["lines_added"] if impl else 0,
            "lines_removed": impl["lines_removed"] if impl else 0,
            "files_created": impl["files_created"] if impl else 0,
            "files_modified": impl["files_modified"] if impl else 0,
            "files_deleted": impl["files_deleted"] if impl else 0,
        }
        prompts.append(row)

        summary["total_prompts"] += 1
        summary["total_input_tokens"] += tk["input"]
        summary["total_output_tokens"] += tk["output"]
        summary["total_tokens"] += tk["total"]
        summary["estimated_cost_usd"] = round(summary["estimated_cost_usd"] + cost, 4)
        intent_split[r["intent"]] = intent_split.get(r["intent"], 0) + 1
        kind_split[r["kind"]] = kind_split.get(r["kind"], 0) + 1

        if impl:
            summary["total_tests_added"] += impl["tests_added"]
            summary["peak_tests_passing"] = max(summary["peak_tests_passing"], impl["tests_passing"])
            summary["total_lines_added"] += impl["lines_added"]
            summary["total_lines_removed"] += impl["lines_removed"]
            summary["total_files_created"] += impl["files_created"]
            summary["total_files_modified"] += impl["files_modified"]
            summary["total_files_deleted"] += impl["files_deleted"]
            summary["total_dependencies_installed"] += impl["dependencies_installed"]
            for f in impl["docs_context_updated"]:
                docs_per_file[f] = docs_per_file.get(f, 0) + 1
                cum_docs += 1
        docs_over_time.append({"index": r["index"], "cumulative_updates": cum_docs})

    summary["intent_split"] = intent_split
    summary["kind_split"] = kind_split
    return {
        "summary": summary,
        "prompts": prompts,
        "intent_split": intent_split,
        "kind_split": kind_split,
        "docs_context": {
            "per_file": docs_per_file,
            "cumulative_over_time": docs_over_time,
        },
    }


def load_and_aggregate(path: str) -> dict:
    return aggregate(load_records(path))
