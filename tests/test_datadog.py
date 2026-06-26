"""Spec for the LiveDatadogAdapter (read-only Datadog REST).

All HTTP is mocked via httpx.MockTransport — these tests need no real keys and
no network. Written test-first (TDD red) before the implementation exists.
"""
from datetime import datetime, timezone

import httpx
import pytest

from app.telemetry.base import DataSource
from app.telemetry.datadog import LiveDatadogAdapter
from app.telemetry.models import EventSource, Severity

API_KEY = "test-api-key"
APP_KEY = "test-app-key"


def _adapter(handler, **kwargs):
    return LiveDatadogAdapter(
        api_key=API_KEY,
        app_key=APP_KEY,
        site="datadoghq.eu",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_is_a_datasource():
    assert issubclass(LiveDatadogAdapter, DataSource)


def test_source_type():
    a = _adapter(lambda req: httpx.Response(200, json={}))
    assert a.source_type == "datadog"


def test_list_metrics_returns_configured_names():
    a = _adapter(
        lambda req: httpx.Response(200, json={}),
        metric_queries={"my.metric": "avg:my.metric{*}"},
    )
    assert a.list_metrics() == ["my.metric"]


def test_unknown_metric_raises_without_http():
    def handler(req):  # pragma: no cover - must not be called
        raise AssertionError("should not hit the network for an unknown metric")

    a = _adapter(handler, metric_queries={"known": "avg:known{*}"})
    with pytest.raises(KeyError):
        a.get_metric("unknown")


def test_get_metric_sends_auth_and_query_and_parses_points():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["host"] = req.url.host
        seen["query"] = req.url.params.get("query")
        seen["dd_api"] = req.headers.get("DD-API-KEY")
        seen["dd_app"] = req.headers.get("DD-APPLICATION-KEY")
        return httpx.Response(200, json={
            "series": [{
                "metric": "api.latency.p95",
                "pointlist": [[1705309200000, 120.0], [1705309260000, 480.0]],
            }],
        })

    a = _adapter(handler, metric_queries={"api.latency.p95": "p95:trace.duration{*}"})
    start = datetime(2024, 1, 15, 9, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)
    s = a.get_metric("api.latency.p95", start=start, end=end)

    assert seen["path"] == "/api/v1/query"
    assert seen["host"] == "api.datadoghq.eu"
    assert seen["query"] == "p95:trace.duration{*}"
    assert seen["dd_api"] == API_KEY
    assert seen["dd_app"] == APP_KEY
    assert [p.value for p in s.points] == [120.0, 480.0]
    assert s.points[0].timestamp == datetime(2024, 1, 15, 9, 0, tzinfo=timezone.utc)


def test_get_metric_handles_empty_series():
    a = _adapter(lambda req: httpx.Response(200, json={"series": []}),
                 metric_queries={"m": "avg:m{*}"})
    s = a.get_metric("m", start=datetime(2024, 1, 15, tzinfo=timezone.utc),
                     end=datetime(2024, 1, 15, 1, tzinfo=timezone.utc))
    assert s.points == []


def test_get_events_parses_and_sorts():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v1/events"
        return httpx.Response(200, json={"events": [
            {"id": 2, "date_happened": 1705309320, "title": "API latency high",
             "text": "p95 over SLO", "alert_type": "error", "tags": ["service:checkout"]},
            {"id": 1, "date_happened": 1705309200, "title": "Deploy v2.4.1 started",
             "text": "rollout", "alert_type": "info", "tags": ["deploy", "service:checkout"]},
        ]})

    a = _adapter(handler)
    start = datetime(2024, 1, 15, 9, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)
    events = a.get_events(start=start, end=end)

    assert [e.id for e in events] == ["1", "2"]  # sorted by time
    assert events[0].source == EventSource.DEPLOY      # classified from tags/title
    assert events[1].severity == Severity.CRITICAL     # alert_type "error"


def test_time_range_is_one_hour_and_tz_aware():
    a = _adapter(lambda req: httpx.Response(200, json={}))
    start, end = a.time_range()
    assert start.tzinfo is not None and end.tzinfo is not None
    assert (end - start).total_seconds() == 3600
