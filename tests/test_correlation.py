"""Correlation layer: Terraform-extracted metrics → resolver → evidence catalog.

Covers the seams added for the correlation layer: metric-query extraction and
alias vocabulary (index), deterministic metric selection (resolver), the
bounded evidence catalog (`metrics=` param), and the adapter merge precedence.
Everything runs offline against fixtures and fakes.
"""
from datetime import datetime, timedelta, timezone

from app.copilot import merged_metric_queries
from app.monitors.index import MonitorsIndex, build_monitors_index, service_vocabulary
from app.monitors.resolver import DEFAULT_TOP_K, select_metrics
from app.reasoning.evidence import build_evidence_catalog
from app.telemetry.base import DataSource
from app.telemetry.models import MetricPoint, MetricSeries

# --- fixture Terraform tree --------------------------------------------------

_MONITOR_TF = '''
resource "datadog_monitor" "audit_event_consumer_failure" {
  for_each = local.query
  query    = "sum(last_5m):sum:ec.centralised_audit.communication_event_dlt_counter{kube_namespace:${env.name}} by {exception,tenant}.as_count() > 0"
}
'''

_DASHBOARD_TF = '''
widget {
  query = "sum:ec.quota_manager.pipeline_processed_counter{$tenant} by {kube_namespace}.as_count()"
}
widget {
  query = "sum:ec.pipeline_qualifier.ingested_communication_consumption_rate{$kube_namespace}"
}
widget {
  query = "sum:ec.surveillance_policy_evaluator.comm_qualified_consumer_error_counter{*}.as_count()"
}
'''


def _fixture_repo(tmp_path):
    monitor = tmp_path / "modules" / "audit_event_consumer_failure"
    monitor.mkdir(parents=True)
    (monitor / "main.tf").write_text(_MONITOR_TF)
    dash = tmp_path / "modules" / "ec_message_processing_summary_dashboard"
    dash.mkdir(parents=True)
    (dash / "dashboard.tf").write_text(_DASHBOARD_TF)
    return str(tmp_path)


_DLT = "ec.centralised_audit.communication_event_dlt_counter"
_PROCESSED = "ec.quota_manager.pipeline_processed_counter"
_CONSUMPTION = "ec.pipeline_qualifier.ingested_communication_consumption_rate"
_POLICY_ERR = "ec.surveillance_policy_evaluator.comm_qualified_consumer_error_counter"


# --- extraction ---------------------------------------------------------------

def test_extracts_normalized_queries_from_monitors_and_dashboards(tmp_path):
    index = build_monitors_index(_fixture_repo(tmp_path))
    # Monitor query: eval-window prefix, interpolated scope, grouping, and
    # threshold are stripped; the counter suffix survives; scope resets to {*}.
    assert index.metric_queries[_DLT] == f"sum:{_DLT}{{*}}.as_count()"
    # Dashboard widget queries, template-variable scopes normalized the same way.
    assert index.metric_queries[_PROCESSED] == f"sum:{_PROCESSED}{{*}}.as_count()"
    assert index.metric_queries[_CONSUMPTION] == f"sum:{_CONSUMPTION}{{*}}"


def test_aliases_derived_from_module_names_and_metric_segments(tmp_path):
    index = build_monitors_index(_fixture_repo(tmp_path))
    # ec_message_processing_summary_dashboard → "message processing", covering
    # every metric that module's widgets query.
    assert set(index.aliases["message processing"]) == {_PROCESSED, _CONSUMPTION, _POLICY_ERR}
    assert index.aliases["quota manager"] == [_PROCESSED]
    # surveillance_ services alias both with and without the prefix.
    assert index.aliases["policy evaluator"] == [_POLICY_ERR]
    assert index.aliases["surveillance policy evaluator"] == [_POLICY_ERR]


# --- resolver -------------------------------------------------------------------

def _index(tmp_path) -> MonitorsIndex:
    return build_monitors_index(_fixture_repo(tmp_path))


def test_alias_phrase_in_question_selects_its_metrics(tmp_path):
    index = _index(tmp_path)
    selected = select_metrics(
        "Is message processing healthy in PROD?", None, index,
        available=set(index.metric_queries),
    )
    assert set(selected) == {_PROCESSED, _CONSUMPTION, _POLICY_ERR}


def test_token_overlap_matches_metric_name_segments(tmp_path):
    index = _index(tmp_path)
    selected = select_metrics(
        "any dlt problems on the audit side?", None, index,
        available=set(index.metric_queries),
    )
    assert selected[0] == _DLT


def test_history_carries_service_context_for_followups(tmp_path):
    index = _index(tmp_path)
    history = [("user", "how is the quota manager doing?"), ("assistant", "…fine…")]
    selected = select_metrics("and over the last day?", history, index,
                              available=set(index.metric_queries))
    assert _PROCESSED in selected


def test_no_signal_falls_back_to_golden_set(tmp_path):
    index = _index(tmp_path)
    selected = select_metrics("is everything healthy?", None, index,
                              available=set(index.metric_queries))
    assert 0 < len(selected) <= DEFAULT_TOP_K
    # per-service throughput + error lenses
    assert _CONSUMPTION in selected and _DLT in selected


def test_only_available_metrics_are_selected(tmp_path):
    index = _index(tmp_path)
    selected = select_metrics("message processing rate?", None, index,
                              available={_PROCESSED})
    assert selected == [_PROCESSED]


def test_empty_registry_selects_nothing():
    empty = MonitorsIndex(monitors=[], dashboards=[], repo_path="")
    assert select_metrics("anything", None, empty, available=set()) == []


# --- resolver + EC knowledge vocabulary -----------------------------------------

def _vocab():
    from app.knowledge.loader import load_knowledge
    from app.knowledge.vocabulary import build_vocabulary

    return build_vocabulary(load_knowledge())


def test_a_knowledge_synonym_selects_the_right_service(tmp_path):
    """"sampler" names no Terraform module and shares no token with any metric
    name — only the EC knowledge layer knows it means the quota manager. Without
    it this question falls through to the generic golden set."""
    index = _index(tmp_path)
    available = set(index.metric_queries)

    blind = select_metrics("is the sampler busy?", None, index, available=available)
    informed = select_metrics("is the sampler busy?", None, index,
                              available=available, vocabulary=_vocab())

    assert _PROCESSED in informed
    assert informed != blind


def test_knowledge_outranks_incidental_token_overlap(tmp_path):
    index = _index(tmp_path)
    selected = select_metrics(
        "how is the sampler doing?", None, index,
        available=set(index.metric_queries), vocabulary=_vocab(),
    )
    assert selected[0] == _PROCESSED


def test_knowledge_never_selects_a_metric_the_registry_lacks(tmp_path):
    """The hint-layer contract at the resolver boundary: the knowledge files
    name many ec.review_service.* metrics; none are in this registry."""
    index = _index(tmp_path)
    selected = select_metrics(
        "how many reviewer groups were created?", None, index,
        available=set(index.metric_queries), vocabulary=_vocab(),
    )
    assert all(m in index.metric_queries for m in selected)


def test_resolver_without_a_vocabulary_is_unchanged(tmp_path):
    """Knowledge is additive. With no vocabulary the resolver must behave
    exactly as it did before this layer existed."""
    index = _index(tmp_path)
    available = set(index.metric_queries)
    assert (
        select_metrics("is everything healthy?", None, index, available=available)
        == select_metrics("is everything healthy?", None, index,
                          available=available, vocabulary=None)
    )


def test_knowledge_selection_still_respects_the_top_k_bound(tmp_path):
    index = _index(tmp_path)
    selected = select_metrics(
        "how is the quota manager and the audit and the qualifier doing?",
        None, index, available=set(index.metric_queries), vocabulary=_vocab(), k=2,
    )
    assert len(selected) <= 2


# --- evidence catalog bounding ---------------------------------------------------

class RecordingSource(DataSource):
    source_type = "fake"

    def __init__(self, metrics: list[str]):
        self._metrics = metrics
        self.queried: list[str] = []

    def list_metrics(self):
        return list(self._metrics)

    def get_metric(self, metric, start=None, end=None, scope=None):
        self.queried.append(metric)
        point = MetricPoint(timestamp=datetime.now(timezone.utc), value=1.0)
        return MetricSeries(metric=metric, points=[point])

    def get_events(self, start=None, end=None, scope=None):
        return []

    def time_range(self):
        now = datetime.now(timezone.utc)
        return now, now


def test_catalog_queries_only_selected_metrics():
    source = RecordingSource([_DLT, _PROCESSED, _CONSUMPTION])
    catalog, _ = build_evidence_catalog(source, metrics=[_PROCESSED, "not.registered"])
    assert source.queried == [_PROCESSED]          # unknown names skipped, no KeyError
    assert set(catalog) == {f"met:{_PROCESSED}"}


def test_catalog_without_selection_keeps_query_all_behavior():
    source = RecordingSource([_DLT, _PROCESSED])
    build_evidence_catalog(source)
    assert source.queried == [_DLT, _PROCESSED]


# --- engine wiring -----------------------------------------------------------------

class _StubLLM:
    def complete(self, system, prompt, deep=False):
        self.last_prompt = prompt
        return ('{"summary": "ok", "facts": [], "hypotheses": [], '
                '"recommendations": [], "unknowns": []}')


def test_engine_bounds_catalog_via_resolver(tmp_path):
    from app.reasoning.engine import ReasoningEngine

    index = _index(tmp_path)
    source = RecordingSource(sorted(index.metric_queries))
    engine = ReasoningEngine(source, _StubLLM(), monitors_index=index)

    engine.investigate("Is message processing healthy?")
    # Only the resolver's selection is queried — not the whole registry.
    assert set(source.queried) == {_PROCESSED, _CONSUMPTION, _POLICY_ERR}


def test_engine_without_registry_keeps_query_all(tmp_path):
    from app.reasoning.engine import ReasoningEngine

    source = RecordingSource([_DLT, _PROCESSED])
    engine = ReasoningEngine(source, _StubLLM(), monitors_index=None)
    engine.investigate("anything at all")
    assert source.queried == [_DLT, _PROCESSED]


def test_engine_bounds_a_large_registry_even_with_no_monitors_index():
    # The live shape: 420 discovered metrics, no Terraform repo. Querying them all
    # would be 420 HTTP calls per question.
    from app.reasoning.engine import ReasoningEngine

    big = sorted(f"ec.svc{i}.processed_counter" for i in range(50))
    source = RecordingSource(big)
    engine = ReasoningEngine(source, _StubLLM(), monitors_index=None)
    engine.investigate("how many are being processed?")
    assert 0 < len(source.queried) <= DEFAULT_TOP_K


def test_engine_bounds_a_large_registry_with_an_empty_monitors_index():
    from app.reasoning.engine import ReasoningEngine

    big = sorted(f"ec.svc{i}.processed_counter" for i in range(50))
    source = RecordingSource(big)
    engine = ReasoningEngine(source, _StubLLM(), monitors_index=_EMPTY_INDEX)
    engine.investigate("anything at all")
    assert 0 < len(source.queried) <= DEFAULT_TOP_K


# --- adapter merge precedence ------------------------------------------------------

def test_merge_precedence_configured_over_extracted():
    extracted = {"ec.a": "sum:ec.a{*}", "ec.b": "sum:ec.b{*}"}
    configured = {"ec.a": "avg:ec.a{env:prod}"}
    merged = merged_metric_queries(extracted, configured)
    assert merged == {"ec.a": "avg:ec.a{env:prod}", "ec.b": "sum:ec.b{*}"}


def test_merge_empty_yields_none_for_adapter_defaults():
    assert merged_metric_queries(None, None) is None
    assert merged_metric_queries({}, {}) is None


# --- namespace-scoped extraction (DATADOG_METRIC_NAMESPACES) ----------------------

_EA_TF = '''
widget {
  query = "avg:ea.review_service.request_latency{*}"
}
'''

_EA_METRIC = "ea.review_service.request_latency"


def _multi_namespace_repo(tmp_path):
    """The ec.* fixture tree plus one module emitting an ea.* metric."""
    _fixture_repo(tmp_path)
    extra = tmp_path / "modules" / "ea_review_service_dashboard"
    extra.mkdir(parents=True)
    (extra / "dashboard.tf").write_text(_EA_TF)
    return str(tmp_path)


def test_extraction_defaults_to_the_ec_namespace(tmp_path):
    # No namespaces configured → today's behavior exactly: ec.* only.
    index = build_monitors_index(_multi_namespace_repo(tmp_path))
    assert _PROCESSED in index.metric_queries
    assert _EA_METRIC not in index.metric_queries


def test_configured_namespaces_widen_extraction_to_each_prefix(tmp_path):
    index = build_monitors_index(
        _multi_namespace_repo(tmp_path), namespaces=("ec.*", "ea.*"))
    assert index.metric_queries[_EA_METRIC] == f"avg:{_EA_METRIC}{{*}}"
    assert _PROCESSED in index.metric_queries          # ec.* still extracted


def test_a_narrowed_namespace_excludes_the_other_prefix(tmp_path):
    index = build_monitors_index(_multi_namespace_repo(tmp_path), namespaces=("ea.*",))
    assert _EA_METRIC in index.metric_queries
    assert _PROCESSED not in index.metric_queries


def test_extracted_ea_metrics_get_service_aliases_too(tmp_path):
    # The alias vocabulary is what lets a user say "review service" — it must be
    # derived for every configured namespace, not just ec.
    index = build_monitors_index(
        _multi_namespace_repo(tmp_path), namespaces=("ec.*", "ea.*"))
    assert index.aliases["review service"] == [_EA_METRIC]


# --- namespace filtering in the adapter merge ------------------------------------

def test_merge_filters_out_metrics_outside_the_namespaces():
    # ec.a is listed as discovered too, so it survives the confirmed-reporting rule
    # and this test isolates namespace filtering (system.cpu.user must go).
    merged = merged_metric_queries(
        {"ec.a": "sum:ec.a{*}"},
        None,
        discovered={"ec.a": "avg:ec.a{*}", "ea.b": "avg:ea.b{*}",
                    "system.cpu.user": "avg:system.cpu.user{*}"},
        namespaces=("ec.*", "ea.*"),
    )
    assert set(merged) == {"ec.a", "ea.b"}


def test_merge_precedence_is_configured_then_extracted_then_discovered():
    merged = merged_metric_queries(
        {"ec.a": "sum:ec.a{*}", "ec.b": "sum:ec.b{*}"},
        {"ec.a": "avg:ec.a{env:prod}"},
        discovered={"ec.a": "avg:ec.a{*}", "ec.b": "avg:ec.b{*}", "ec.c": "avg:ec.c{*}"},
        namespaces=("ec.*",),
    )
    # configured wins outright; extracted keeps its real aggregation over the
    # generic discovered one; discovered contributes only what nothing else has.
    assert merged == {
        "ec.a": "avg:ec.a{env:prod}",
        "ec.b": "sum:ec.b{*}",
        "ec.c": "avg:ec.c{*}",
    }


def test_explicitly_configured_metrics_survive_the_namespace_filter():
    merged = merged_metric_queries(
        None, {"system.cpu.user": "avg:system.cpu.user{*}"}, namespaces=("ec.*",))
    assert merged == {"system.cpu.user": "avg:system.cpu.user{*}"}


def test_service_vocabulary_derives_guard_terms_from_metric_names():
    assert service_vocabulary([
        "ec.quota_manager.pipeline_processed_counter",
        "ec.surveillance_policy_evaluator.error_counter",
    ]) == ("policy evaluator", "quota manager", "surveillance policy evaluator")


def test_service_vocabulary_drops_segments_too_short_to_match_safely():
    # Guard vocabulary is SUBSTRING-matched, so a 1-2 character term would appear
    # in nearly every message and fast-allow everything, disabling the guard.
    assert service_vocabulary(["ec.a.b", "ec.qm.count", "ec.audit.count"]) == ("audit",)


def test_service_vocabulary_ignores_names_with_no_service_segment():
    assert service_vocabulary(["ec", "flat_name"]) == ()


# --- the resolver must work from the LIVE registry, not only Terraform ----------
# Verified live 2026-08-05: with MONITORS_REPO_PATH unset, discovery alone yields a
# 420-metric registry while the Terraform index is empty. The resolver used to bail
# on an empty index, which meant (a) zero metric evidence and (b) the engine falling
# back to query-everything — 420 HTTP calls per question.

_EMPTY_INDEX = MonitorsIndex(monitors=[], dashboards=[], repo_path="")

_LIVE_REGISTRY = {
    "ec.alerting_service.alert_published_counter",
    "ec.alerting_service.alert_outbox_event_error_counter",
    "ec.quota_manager.pipeline_processed_counter",
    "ec.quota_manager.pipeline_dlt_counter",
    "ec.review_service.request_latency",
    "ec.indexer.documents_indexed_rate",
}


def test_resolver_matches_service_phrases_derived_from_live_metric_names():
    # "alerting service" is never mentioned in any .tf file here — it comes from
    # the metric names themselves.
    picked = select_metrics(
        "any errors in the alerting service?", None, _EMPTY_INDEX, available=_LIVE_REGISTRY)
    # The alias match outranks incidental token overlap ("service" appears in
    # ec.review_service.* too), so the alerting metrics come first.
    assert picked[:2] == [
        "ec.alerting_service.alert_outbox_event_error_counter",
        "ec.alerting_service.alert_published_counter",
    ]


def test_resolver_matches_token_overlap_against_live_metric_names():
    picked = select_metrics(
        "what is the request latency?", None, _EMPTY_INDEX, available=_LIVE_REGISTRY)
    assert "ec.review_service.request_latency" in picked


def test_resolver_falls_back_to_a_golden_set_from_the_live_registry():
    picked = select_metrics(
        "is everything healthy?", None, _EMPTY_INDEX, available=_LIVE_REGISTRY)
    assert picked, "a vague question must still get real telemetry"
    assert len(picked) <= DEFAULT_TOP_K


def test_resolver_with_no_available_metrics_selects_nothing():
    assert select_metrics("anything", None, _EMPTY_INDEX, available=set()) == []


def test_resolver_never_returns_more_than_k():
    big = {f"ec.svc{i}.processed_counter" for i in range(50)}
    assert len(select_metrics("processed", None, _EMPTY_INDEX, available=big)) <= DEFAULT_TOP_K


# --- extracted metrics must be confirmed reporting -------------------------------
# The live probe found ec.centralised_audit.communication_event_dlt_counter in the
# .tf files but NOT reporting (0 series, 0 tags). A metric that can't return data
# must not sit in the registry where the resolver can pick it and produce an
# investigation with no supporting telemetry.

def test_extracted_metric_confirmed_by_discovery_keeps_its_real_aggregation():
    merged = merged_metric_queries(
        {"ec.a": "sum:ec.a{*}.as_count()"},
        None,
        discovered={"ec.a": "avg:ec.a{*}"},
        namespaces=("ec.*",),
    )
    assert merged == {"ec.a": "sum:ec.a{*}.as_count()"}


def test_extracted_metric_not_reporting_is_dropped():
    merged = merged_metric_queries(
        {"ec.dead": "sum:ec.dead{*}.as_count()", "ec.live": "sum:ec.live{*}"},
        None,
        discovered={"ec.live": "avg:ec.live{*}"},
        namespaces=("ec.*",),
    )
    assert set(merged) == {"ec.live"}


def test_when_discovery_returns_nothing_the_full_extracted_set_survives():
    # Discovery failing (or being unconfigured) must not empty the registry —
    # that's the graceful-degradation path.
    extracted = {"ec.a": "sum:ec.a{*}", "ec.b": "sum:ec.b{*}"}
    assert merged_metric_queries(
        extracted, None, discovered={}, namespaces=("ec.*",)) == extracted
    assert merged_metric_queries(
        extracted, None, discovered=None, namespaces=("ec.*",)) == extracted


def test_configured_metrics_never_need_confirming():
    # An explicit DATADOG_METRIC_QUERIES entry is the human overriding us.
    merged = merged_metric_queries(
        None,
        {"ec.pinned": "sum:ec.pinned{*}"},
        discovered={"ec.other": "avg:ec.other{*}"},
        namespaces=("ec.*",),
    )
    assert merged["ec.pinned"] == "sum:ec.pinned{*}"


def test_merge_drops_statistical_sub_metrics_from_the_registry():
    merged = merged_metric_queries(
        None, None,
        discovered={
            "ec.svc.latency": "avg:ec.svc.latency{*}",
            "ec.svc.latency.count": "avg:ec.svc.latency.count{*}",
            "ec.svc.latency.max": "avg:ec.svc.latency.max{*}",
        },
        namespaces=("ec.*",),
    )
    assert set(merged) == {"ec.svc.latency"}


def test_merge_returns_none_when_the_filter_empties_the_registry():
    # None means "adapter defaults" — but with namespaces set the adapter must NOT
    # fall back to system.* defaults, so it has to be able to see an empty result.
    assert merged_metric_queries(
        {"system.cpu.user": "avg:system.cpu.user{*}"}, None, namespaces=("ec.*",)) == {}


# --- timeline bounding ------------------------------------------------------------
# A live org returns ~1000 monitor events an hour (measured 2026-08-05), which made
# the workspace's "Timeline of Events" section a 1000-row list on every reply.

def test_timeline_is_bounded_and_prefers_significant_events():
    from app.telemetry.models import EventSource, Severity, TelemetryEvent
    from app.reasoning.timeline import MAX_TIMELINE_EVENTS, build_timeline

    base = datetime(2026, 8, 5, tzinfo=timezone.utc)
    noise = [
        TelemetryEvent(id=f"i{n}", timestamp=base + timedelta(minutes=n),
                       source=EventSource.METRIC, title="routine", severity=Severity.INFO)
        for n in range(400)
    ]
    alerts = [
        TelemetryEvent(id=f"c{n}", timestamp=base + timedelta(minutes=500 + n),
                       source=EventSource.METRIC, title="alert", severity=Severity.CRITICAL)
        for n in range(5)
    ]
    out = build_timeline(noise + alerts)
    assert len(out) == MAX_TIMELINE_EVENTS
    # Every critical event survives the trim...
    assert {e.id for e in alerts} <= {e.id for e in out}
    # ...and the result is still chronological.
    assert [e.timestamp for e in out] == sorted(e.timestamp for e in out)


def test_a_small_timeline_is_returned_whole():
    from app.telemetry.models import EventSource, Severity, TelemetryEvent
    from app.reasoning.timeline import build_timeline

    base = datetime(2026, 8, 5, tzinfo=timezone.utc)
    events = [
        TelemetryEvent(id=str(n), timestamp=base + timedelta(minutes=-n),
                       source=EventSource.METRIC, title="t", severity=Severity.INFO)
        for n in range(5)
    ]
    out = build_timeline(events)
    assert len(out) == 5
    assert [e.timestamp for e in out] == sorted(e.timestamp for e in out)
