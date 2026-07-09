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


# ---------- timeline / by-day (Tab 2) ----------

def _dated(index, date, intent="implementation", hh=12, **impl):
    """A record stamped with a prompt timestamp on the given calendar date."""
    r = _impl_rec(index, **impl) if intent == "implementation" else _plan_rec(index)
    r["prompt_ts"] = f"{date}T{hh:02d}:00:00.000Z"
    return r


def test_prompt_rows_include_date_and_timestamp():
    recs = [_dated(1, "2026-06-26"), _plan_rec(2)]  # rec 2 has no prompt_ts
    rows = A.aggregate(recs)["prompts"]
    assert rows[0]["date"] == "2026-06-26"
    assert rows[0]["prompt_ts"] == "2026-06-26T12:00:00.000Z"
    assert rows[1]["date"] == "unknown"
    assert rows[1]["prompt_ts"] is None


def test_by_day_groups_and_orders_chronologically():
    recs = [_dated(3, "2026-06-28"), _dated(1, "2026-06-26"), _dated(2, "2026-06-26")]
    days = A.aggregate(recs)["by_day"]
    assert [d["date"] for d in days] == ["2026-06-26", "2026-06-28"]
    assert days[0]["prompts"] == 2
    assert days[1]["prompts"] == 1


def test_by_day_sums_metrics_per_day():
    recs = [
        _dated(1, "2026-06-26", tests_added=2, lines_added=100, lines_removed=10, files_created=3),
        _dated(2, "2026-06-26", tests_added=3, lines_added=50, files_modified=2),
        _dated(3, "2026-06-27", tests_added=1, lines_added=5),
    ]
    days = {d["date"]: d for d in A.aggregate(recs)["by_day"]}
    d26 = days["2026-06-26"]
    assert d26["tests_added"] == 5
    assert d26["lines_added"] == 150
    assert d26["files_created"] == 3 and d26["files_modified"] == 2
    # each _impl_rec carries input 10 / output 20 / total 36
    assert d26["input_tokens"] == 20 and d26["output_tokens"] == 40 and d26["total_tokens"] == 72
    assert days["2026-06-27"]["lines_added"] == 5


def test_by_day_peak_and_cumulative_tests():
    recs = [
        _dated(1, "2026-06-26", tests_passing=11),
        _dated(2, "2026-06-26", tests_passing=24),
        _dated(3, "2026-06-27", intent="planning_qa"),  # no impl -> no tests that day
    ]
    days = {d["date"]: d for d in A.aggregate(recs)["by_day"]}
    assert days["2026-06-26"]["peak_tests_passing"] == 24
    assert days["2026-06-26"]["cumulative_peak_tests"] == 24
    assert days["2026-06-27"]["peak_tests_passing"] == 0        # none that day
    assert days["2026-06-27"]["cumulative_peak_tests"] == 24    # carried forward


def test_by_day_cumulative_cost_is_monotonic():
    recs = [_dated(1, "2026-06-26", tests_passing=1),
            _dated(2, "2026-06-27", tests_passing=1),
            _dated(3, "2026-06-28", tests_passing=1)]
    agg = A.aggregate(recs)
    cums = [d["cumulative_cost_usd"] for d in agg["by_day"]]
    assert cums == sorted(cums)                                  # non-decreasing
    assert cums[-1] == pytest.approx(agg["summary"]["estimated_cost_usd"], abs=1e-4)


def test_timeline_summary_first_last_active_busiest():
    recs = [_dated(1, "2026-06-26"), _dated(2, "2026-06-28"),
            _dated(3, "2026-06-28"), _dated(4, "2026-06-28")]
    ts = A.aggregate(recs)["timeline_summary"]
    assert ts["first_date"] == "2026-06-26"
    assert ts["last_date"] == "2026-06-28"
    assert ts["active_days"] == 2
    assert ts["busiest_day"] == {"date": "2026-06-28", "prompts": 3}


def test_by_day_tolerates_missing_timestamps():
    recs = [_dated(1, "2026-06-26"), _plan_rec(2), {"index": 3}]  # 2 and 3 lack prompt_ts
    agg = A.aggregate(recs)                                        # must not raise
    days = {d["date"]: d for d in agg["by_day"]}
    assert "2026-06-26" in days and "unknown" in days
    assert days["unknown"]["prompts"] == 2
    assert agg["by_day"][-1]["date"] == "unknown"                 # unknown sorts last
    # the summary ignores the unknown bucket
    assert agg["timeline_summary"]["active_days"] == 1
    assert agg["timeline_summary"]["first_date"] == "2026-06-26"


def test_aggregate_empty_has_empty_timeline():
    agg = A.aggregate([])
    assert agg["by_day"] == []
    ts = agg["timeline_summary"]
    assert ts["first_date"] is None and ts["last_date"] is None
    assert ts["active_days"] == 0
    assert ts["busiest_day"] is None


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


def test_api_metrics_includes_timeline(client):
    data = client.get("/api/metrics").json()
    assert "by_day" in data
    assert "timeline_summary" in data


def test_dashboard_html_has_two_tabs(client):
    html = client.get("/").text
    assert "Overview" in html
    assert "Timeline" in html
    assert "tab-timeline" in html


# ---------- tab switching (must not depend on JS running) ----------

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parent.parent / "metrics" / "static"


def test_tabs_are_radio_driven_with_one_default_checked():
    html = (_STATIC / "dashboard.html").read_text()
    radios = re.findall(r"<input[^>]*class=\"tabradio\"[^>]*>", html)
    assert len(radios) == 2                              # two real tabs
    assert sum("checked" in r for r in radios) == 1      # exactly one active by default
    # labels point at the radios; views exist with matching ids
    for key in ("overview", "timeline"):
        assert f'id="r-{key}"' in html
        assert f'for="r-{key}"' in html
        assert f'id="tab-{key}"' in html


def test_tab_markup_order_supports_sibling_selector():
    # The '~' combinator needs radios BEFORE the views, sharing a parent.
    html = (_STATIC / "dashboard.html").read_text()
    assert html.index('id="r-timeline"') < html.index('id="tab-overview"')
    assert html.index('id="tab-overview"') < html.index('id="tab-timeline"')


def test_tab_switching_is_pure_css_no_js_required():
    css = (_STATIC / "dashboard.css").read_text()
    norm = css.replace(" ", "")
    assert ".tabview{display:none" in norm                 # views hidden by default
    # a checked-radio sibling rule reveals each view — switching needs no JavaScript
    assert "#r-overview:checked~#tab-overview" in norm
    assert "#r-timeline:checked~#tab-timeline" in norm
    assert ".tabradio" in css                               # the radios themselves are hidden


def test_normalize_derives_tokens_missing():
    # older records have no explicit flag -> derive it from zero total
    z = A.normalize({"index": 1, "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "total": 0}})
    assert z["tokens_missing"] is True
    ok = A.normalize({"index": 2, "tokens": {"output": 100, "total": 100}})
    assert ok["tokens_missing"] is False
    # explicit flag is honored even if (hypothetically) totals disagree
    flagged = A.normalize({"index": 3, "tokens_missing": True, "tokens": {"output": 5, "total": 5}})
    assert flagged["tokens_missing"] is True


def test_aggregate_counts_and_surfaces_tokens_missing():
    recs = [
        {"index": 1, "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "total": 0}},
        {"index": 2, "tokens": {"input": 5, "output": 50, "cache_read": 0, "cache_creation": 0, "total": 55}},
    ]
    agg = A.aggregate(recs)
    assert agg["summary"]["tokens_missing_count"] == 1
    by_index = {p["index"]: p for p in agg["prompts"]}
    assert by_index[1]["tokens_missing"] is True
    assert by_index[2]["tokens_missing"] is False


def test_procedural_flag_is_surfaced_and_counted():
    recs = [
        {"index": 1, "procedural": True, "tokens": {"output": 10, "total": 10}},
        {"index": 2, "tokens": {"output": 20, "total": 20}},          # not procedural
    ]
    agg = A.aggregate(recs)
    assert agg["summary"]["procedural_count"] == 1
    by_index = {p["index"]: p for p in agg["prompts"]}
    assert by_index[1]["procedural"] is True
    assert by_index[2]["procedural"] is False   # default when absent


def test_procedural_does_not_alter_totals():
    # curation is a view concern only — totals still count every record
    recs = [
        {"index": 1, "procedural": True, "tokens": {"output": 100, "total": 100}},
        {"index": 2, "tokens": {"output": 100, "total": 100}},
    ]
    s = A.aggregate(recs)["summary"]
    assert s["total_prompts"] == 2
    assert s["total_tokens"] == 200          # procedural rows still counted in totals
