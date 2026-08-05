"""Spec for the LiveDatadogAdapter (read-only Datadog REST).

All HTTP is mocked via httpx.MockTransport — these tests need no real keys and
no network. Written test-first (TDD red) before the implementation exists.
"""
from datetime import datetime, timezone

import httpx
import pytest

from app.telemetry.base import DataSource
from app.telemetry.datadog import LiveDatadogAdapter, discover_metric_names
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
    a = _adapter(_scopes_handler(), metric_queries={"ec.a": "sum:ec.a{*}.as_count()"})
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

    a = _adapter(handler, metric_queries={"ec.a": "sum:ec.a{*}"})
    a.list_scopes(environments=["prod", "staging"])
    assert "(env:prod OR env:staging)" in seen["tenant_q"]


def test_tag_discovery_groups_an_in_scope_metric_not_an_infra_default():
    # DATADOG_DISCOVERY_METRIC is retired: the tag-value query is built from a
    # metric that's actually in scope, so discovery can't depend on system.*.
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.setdefault("queries", []).append(req.url.params.get("query") or "")
        return httpx.Response(200, json={"series": []})

    a = _adapter(handler, metric_queries={"ec.quota_manager.count": "sum:ec.quota_manager.count{*}"})
    a.list_scopes()
    assert seen["queries"][0] == "ec.quota_manager.count{*} by {env}"
    assert not any("system.cpu.user" in q for q in seen["queries"])


# --- the environment tag key is configurable, like the tenant one -----------
# Verified live 2026-08-05: this org has NO `env` tag (grouping by it yields the
# single placeholder series `env:N/A`); the environment dimension is carried by
# `kube_namespace` (ep-perflab-uat, ep-smarsh-staging). A hardcoded "env" would
# make every environment filter silently match nothing.

def test_scope_filter_uses_the_configured_environment_tag():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["query"] = req.url.params.get("query")
        return httpx.Response(200, json={"series": []})

    a = _adapter(handler, metric_queries={"ec.m": "avg:ec.m{*}"},
                 env_tag="kube_namespace", tenant_tag="tenant")
    a.get_metric("ec.m", scope=Scope(environments=["ep-smarsh-staging"], tenants=["msanity"],
                                     start=_S0, end=_S0 + timedelta(hours=1)))
    assert "kube_namespace:ep-smarsh-staging" in seen["query"]
    assert "tenant:msanity" in seen["query"]
    assert "env:" not in seen["query"]


def test_tag_discovery_groups_by_the_configured_environment_tag():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.setdefault("queries", []).append(req.url.params.get("query") or "")
        return httpx.Response(200, json={"series": []})

    a = _adapter(handler, metric_queries={"ec.m": "avg:ec.m{*}"}, env_tag="kube_namespace")
    a.list_scopes()
    assert seen["queries"][0] == "ec.m{*} by {kube_namespace}"


def test_tenant_discovery_narrows_by_the_configured_environment_tag():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        q = req.url.params.get("query") or ""
        if "by {tenant}" in q:
            seen["q"] = q
        return httpx.Response(200, json={"series": []})

    a = _adapter(handler, metric_queries={"ec.m": "avg:ec.m{*}"},
                 env_tag="kube_namespace", tenant_tag="tenant")
    a.list_scopes(environments=["ep-perflab-uat", "ep-smarsh-staging"])
    assert "(kube_namespace:ep-perflab-uat OR kube_namespace:ep-smarsh-staging)" in seen["q"]


def test_event_tag_filter_uses_the_configured_environment_tag():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["tags"] = req.url.params.get("tags")
        return httpx.Response(200, json={"events": []})

    a = _adapter(handler, metric_queries={"ec.m": "avg:ec.m{*}"},
                 env_tag="kube_namespace", tenant_tag="tenant")
    a.get_events(scope=Scope(environments=["ep-smarsh-staging"], tenants=["msanity"],
                             start=_S0, end=_S0 + timedelta(hours=1)))
    assert seen["tags"] == "kube_namespace:ep-smarsh-staging,tenant:msanity"


def test_environment_tag_defaults_to_env():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.setdefault("queries", []).append(req.url.params.get("query") or "")
        return httpx.Response(200, json={"series": []})

    a = _adapter(handler, metric_queries={"ec.m": "avg:ec.m{*}"})
    a.list_scopes()
    assert "by {env}" in seen["queries"][0]


def test_discovered_tag_values_drop_datadogs_na_placeholder():
    # Grouping by a tag the metric doesn't carry yields a literal "N/A" series;
    # offering "N/A" as a selectable environment/tenant in the @ menu is noise.
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"series": [
            {"tag_set": ["kube_namespace:N/A"]},
            {"tag_set": ["kube_namespace:ep-smarsh-staging"]},
            {"tag_set": ["kube_namespace:ep-perflab-uat"]},
        ]})

    a = _adapter(handler, metric_queries={"ec.m": "avg:ec.m{*}"}, env_tag="kube_namespace")
    assert a.list_scopes()["environments"] == ["ep-perflab-uat", "ep-smarsh-staging"]


def test_tag_discovery_with_an_empty_registry_makes_no_http_call():
    def handler(req):  # pragma: no cover - must not be called
        raise AssertionError("no metric in scope -> nothing to group by")

    a = _adapter(handler, metric_queries={})
    assert a.list_scopes() == {"environments": [], "tenants": []}


# --- discover_metric_names: live metric-name discovery, namespace-filtered ---

def _metrics_list_handler(payload, status=200):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v1/metrics"
        assert req.url.params.get("from")           # a lookback window is required
        return httpx.Response(status, json=payload)
    return handler


def _discover(handler, patterns=("ec.*",)):
    return discover_metric_names(
        patterns, access_token="t", site="datadoghq.eu",
        transport=httpx.MockTransport(handler),
    )


def test_discovers_metric_names_within_the_namespaces():
    names = _discover(_metrics_list_handler(
        {"metrics": ["ec.quota_manager.count", "ec.review.latency"]}))
    assert names == ["ec.quota_manager.count", "ec.review.latency"]


def test_discovery_drops_names_outside_the_namespaces():
    names = _discover(_metrics_list_handler(
        {"metrics": ["ec.a", "system.cpu.user", "trace.http.duration", "ea.b"]}))
    assert names == ["ec.a"]


def test_discovery_honours_multiple_namespaces():
    names = _discover(
        _metrics_list_handler({"metrics": ["ec.a", "ea.b", "system.cpu.user"]}),
        patterns=("ec.*", "ea.*"),
    )
    assert names == ["ea.b", "ec.a"]          # sorted for a deterministic registry


def test_discovery_also_reads_the_v2_style_data_shape():
    # Tolerant parsing: the exact org/endpoint shape is unverified until the live
    # probe runs, so a {"data": [{"id": ...}]} body must work too.
    names = _discover(_metrics_list_handler(
        {"data": [{"id": "ec.a", "type": "metrics"}, {"id": "system.cpu.user"}]}))
    assert names == ["ec.a"]


def test_discovery_returns_empty_on_an_http_error():
    # Best-effort by design: the app falls back to Terraform-extracted metrics
    # rather than failing to start.
    assert _discover(_metrics_list_handler({"errors": ["Forbidden"]}, status=403)) == []


def test_discovery_returns_empty_on_an_unexpected_shape():
    assert _discover(_metrics_list_handler({"unexpected": True})) == []
    assert _discover(_metrics_list_handler([1, 2, 3])) == []


def test_discovery_without_namespaces_returns_nothing():
    def handler(req):  # pragma: no cover - must not be called
        raise AssertionError("no namespace scope -> no discovery call")

    assert _discover(handler, patterns=()) == []
