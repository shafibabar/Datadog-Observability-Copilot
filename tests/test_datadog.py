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


def test_accepts_verify_option_for_corporate_ca():
    # verify may be a CA-bundle path or bool (TLS-inspection proxies); construction
    # and queries must work regardless (the injected transport bypasses real TLS).
    a = LiveDatadogAdapter(
        access_token="t", verify="/etc/ssl/corp.pem",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"series": []})),
        metric_queries={"m": "avg:m{*}"},
    )
    s = a.get_metric("m", start=datetime(2024, 1, 15, tzinfo=timezone.utc),
                     end=datetime(2024, 1, 15, 1, tzinfo=timezone.utc))
    assert s.points == []


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


def test_access_token_uses_bearer_auth_and_no_key_headers():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("Authorization")
        seen["dd_api"] = req.headers.get("DD-API-KEY")
        seen["dd_app"] = req.headers.get("DD-APPLICATION-KEY")
        return httpx.Response(200, json={"series": []})

    a = LiveDatadogAdapter(
        access_token="pat-secret",
        site="datadoghq.eu",
        transport=httpx.MockTransport(handler),
        metric_queries={"m": "avg:m{*}"},
    )
    a.get_metric("m", start=datetime(2024, 1, 15, tzinfo=timezone.utc),
                 end=datetime(2024, 1, 15, 1, tzinfo=timezone.utc))

    assert seen["auth"] == "Bearer pat-secret"
    # A PAT authenticates on its own — the legacy key headers are not sent.
    assert seen["dd_api"] is None
    assert seen["dd_app"] is None


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


# --- scope: env/tenant become the Datadog query filter --------------------

from datetime import timedelta  # noqa: E402

from app.telemetry.models import Scope  # noqa: E402

_S0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _capture_query(**kwargs):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["query"] = req.url.params.get("query")
        seen["from"] = req.url.params.get("from")
        seen["to"] = req.url.params.get("to")
        seen["tags"] = req.url.params.get("tags")
        return httpx.Response(200, json={"series": []})

    return _adapter(handler, metric_queries={"m": "avg:m{*}"}, **kwargs), seen


def test_no_scope_keeps_wildcard():
    a, seen = _capture_query()
    a.get_metric("m", start=_S0, end=_S0 + timedelta(hours=1))
    assert seen["query"] == "avg:m{*}"


def test_scope_single_env_has_no_parens():
    a, seen = _capture_query()
    a.get_metric("m", scope=Scope(environments=["prod"], start=_S0, end=_S0 + timedelta(hours=1)))
    assert seen["query"] == "avg:m{env:prod}"


def test_scope_builds_env_or_and_tenant_and_filter():
    a, seen = _capture_query()
    a.get_metric("m", scope=Scope(environments=["prod", "staging"], tenants=["acme"],
                                  start=_S0, end=_S0 + timedelta(hours=1)))
    assert seen["query"] == "avg:m{(env:prod OR env:staging) AND tenant:acme}"


def test_tenant_tag_is_configurable():
    a, seen = _capture_query(tenant_tag="customer")
    a.get_metric("m", scope=Scope(tenants=["acme"], start=_S0, end=_S0 + timedelta(hours=1)))
    assert seen["query"] == "avg:m{customer:acme}"


def test_scope_window_drives_metric_query_range():
    a, seen = _capture_query()
    end = _S0 + timedelta(hours=2)
    a.get_metric("m", scope=Scope(environments=["prod"], start=_S0, end=end))
    assert seen["from"] == str(int(_S0.timestamp()))
    assert seen["to"] == str(int(end.timestamp()))


def test_get_events_filters_single_valued_dims_by_tags():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["tags"] = req.url.params.get("tags")
        seen["start"] = req.url.params.get("start")
        return httpx.Response(200, json={"events": []})

    a = _adapter(handler, tenant_tag="tenant")
    a.get_events(scope=Scope(environments=["prod"], tenants=["acme"],
                             start=_S0, end=_S0 + timedelta(hours=1)))
    assert seen["tags"] == "env:prod,tenant:acme"
    assert seen["start"] == str(int(_S0.timestamp()))


# --- list_scopes: enumerate selectable environments / tenants -------------

def _scopes_handler():
    def handler(req: httpx.Request) -> httpx.Response:
        q = req.url.params.get("query") or ""
        if "by {env}" in q:
            return httpx.Response(200, json={"series": [
                {"tag_set": ["env:prod"]}, {"tag_set": ["env:staging"]}]})
        if "by {tenant}" in q:
            return httpx.Response(200, json={"series": [
                {"tag_set": ["tenant:acme"]}, {"tag_set": ["tenant:globex"]}]})
        return httpx.Response(200, json={"series": []})
    return handler


def test_list_scopes_returns_distinct_env_and_tenant_values():
    a = _adapter(_scopes_handler(), discovery_metric="system.cpu.user")
    scopes = a.list_scopes()
    assert scopes["environments"] == ["prod", "staging"]
    assert scopes["tenants"] == ["acme", "globex"]


def test_list_scopes_scopes_tenants_to_selected_environments():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        q = req.url.params.get("query") or ""
        if "by {tenant}" in q:
            seen["tenant_q"] = q
        return httpx.Response(200, json={"series": []})

    a = _adapter(handler, discovery_metric="system.cpu.user")
    a.list_scopes(environments=["prod", "staging"])
    assert "(env:prod OR env:staging)" in seen["tenant_q"]
