"""Spec for the dashboard data layer (metrics/analytics.py + metrics/dashboard.py).

The loader/aggregator must be **robust to schema evolution and bad data**: skip
malformed lines, default missing fields, ignore unknown fields, and tolerate a
future schema_version — so data collected after any future prompt can never break
the dashboard. Aggregations are pure and unit-tested; the FastAPI surface is
tested with TestClient against a temp JSONL.
"""
import json

import pytest
from fastapi.testclient import TestClient

from metrics import analytics as A
from metrics.dashboard import create_app


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _impl_rec(index, **impl):
    base = {"tests_added": 0, "tests_passing": 0, "lines_added": 0, "lines_removed": 0,
            "files_created": 0, "files_modified": 0, "files_deleted": 0,
            "dependencies_installed": 0, "docs_context_updated": []}
    base.update(impl)
    return {"schema_version": 1, "index": index, "intent": "implementation",
            "kind": "user_prompt", "summary": f"impl {index}", "duration_sec": 100,
            "tokens": {"input": 10, "output": 20, "cache_read": 5, "cache_creation": 1, "total": 36},
            "implementation": base}


def _plan_rec(index):
    return {"schema_version": 1, "index": index, "intent": "planning_qa",
            "kind": "user_prompt", "summary": f"plan {index}", "duration_sec": 30,
            "tokens": {"input": 5, "output": 8, "cache_read": 2, "cache_creation": 0, "total": 15}}


# ---------- tolerant loading ----------

def test_load_skips_malformed_and_blank_lines(tmp_path):
    p = tmp_path / "prompts.jsonl"
    p.write_text(
        json.dumps(_plan_rec(1)) + "\n"
        + "\n"                       # blank
        + "{not valid json}\n"        # malformed
        + json.dumps(_plan_rec(2)) + "\n"
    )
    recs = A.load_records(str(p))
    assert [r["index"] for r in recs] == [1, 2]


def test_load_missing_file_returns_empty(tmp_path):
    assert A.load_records(str(tmp_path / "nope.jsonl")) == []


def test_normalize_defaults_missing_fields():
    n = A.normalize({"index": 1})            # almost everything missing
    assert n["intent"] == "planning_qa"
    assert n["kind"] == "user_prompt"
    assert n["tokens"]["input"] == 0 and n["tokens"]["total"] == 0
    assert n["implementation"] is None


def test_normalize_ignores_unknown_and_future_fields():
    rec = {"schema_version": 99, "index": 2, "intent": "implementation",
           "brand_new_field": {"x": 1}, "tokens": {"input": 3, "output": 4},
           "implementation": {"tests_passing": 7, "surprise": "ok"}}
    n = A.normalize(rec)                       # must not raise
    assert n["tokens"]["total"] == 7          # derived when absent
    assert n["implementation"]["tests_passing"] == 7


# ---------- aggregation ----------

def test_aggregate_empty_is_safe():
    agg = A.aggregate([])
    assert agg["summary"]["total_prompts"] == 0
    assert agg["prompts"] == []
    assert agg["intent_split"] == {"planning_qa": 0, "implementation": 0}


def test_aggregate_summary_and_splits():
    recs = [_plan_rec(1), _impl_rec(2, tests_passing=11, lines_added=100, lines_removed=10,
                                    files_created=3, dependencies_installed=2),
            _impl_rec(3, tests_passing=24, lines_added=50, files_modified=2)]
    agg = A.aggregate(recs)
    s = agg["summary"]
    assert s["total_prompts"] == 3
    assert s["intent_split"]["implementation"] == 2
    assert s["peak_tests_passing"] == 24
    assert s["total_lines_added"] == 150
    assert s["total_files_created"] == 3
    assert s["total_dependencies_installed"] == 2
    assert agg["intent_split"] == {"planning_qa": 1, "implementation": 2}


def test_aggregate_per_prompt_rows_with_cumulative_tokens():
    recs = [_plan_rec(1), _impl_rec(2, tests_passing=11)]
    rows = A.aggregate(recs)["prompts"]
    assert [r["index"] for r in rows] == [1, 2]
    # cumulative output tokens run across prompts
    assert rows[0]["cumulative_output"] == 8
    assert rows[1]["cumulative_output"] == 8 + 20
    assert rows[1]["tests_passing"] == 11
    assert rows[0]["tests_passing"] is None     # planning has no test count


def test_aggregate_docs_context_growth():
    recs = [
        _impl_rec(1, docs_context_updated=["STATE.md", "TESTING.md"]),
        _impl_rec(2, docs_context_updated=["STATE.md"]),
    ]
    dc = A.aggregate(recs)["docs_context"]
    assert dc["per_file"]["STATE.md"] == 2
    assert dc["per_file"]["TESTING.md"] == 1
    assert dc["cumulative_over_time"][-1]["cumulative_updates"] == 3


def test_cost_estimate_is_monotonic_and_positive():
    cheap = A.estimate_cost({"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0})
    dear = A.estimate_cost({"input": 1000, "output": 1000, "cache_read": 1000, "cache_creation": 1000})
    assert cheap == 0
    assert dear > 0


def test_aggregate_includes_cost_estimate():
    agg = A.aggregate([_impl_rec(1, tests_passing=11)])
    assert agg["summary"]["estimated_cost_usd"] >= 0
    assert "cost_usd" in agg["prompts"][0]


# ---------- FastAPI surface ----------

@pytest.fixture
def client(tmp_path):
    p = tmp_path / "prompts.jsonl"
    _write(p, [_plan_rec(1), _impl_rec(2, tests_passing=11, lines_added=20)])
    return TestClient(create_app(str(p)))


def test_api_metrics_returns_aggregate(client):
    r = client.get("/api/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["total_prompts"] == 2
    assert len(data["prompts"]) == 2


def test_api_metrics_survives_malformed_file(tmp_path):
    p = tmp_path / "prompts.jsonl"
    p.write_text(json.dumps(_plan_rec(1)) + "\n{broken\n")
    r = TestClient(create_app(str(p))).get("/api/metrics")
    assert r.status_code == 200
    assert r.json()["summary"]["total_prompts"] == 1


def test_api_metrics_empty_when_no_file(tmp_path):
    r = TestClient(create_app(str(tmp_path / "missing.jsonl"))).get("/api/metrics")
    assert r.status_code == 200
    assert r.json()["summary"]["total_prompts"] == 0


def test_dashboard_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Vibe" in r.text or "Metrics" in r.text
