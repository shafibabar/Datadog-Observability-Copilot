"""Correlation layer: Terraform-extracted metrics → resolver → evidence catalog.

Covers the seams added for the correlation layer: metric-query extraction and
alias vocabulary (index), deterministic metric selection (resolver), the
bounded evidence catalog (`metrics=` param), and the adapter merge precedence.
Everything runs offline against fixtures and fakes.
"""
from datetime import datetime, timezone

from app.copilot import merged_metric_queries
from app.monitors.index import MonitorsIndex, build_monitors_index
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


# --- adapter merge precedence ------------------------------------------------------

def test_merge_precedence_configured_over_extracted():
    extracted = {"ec.a": "sum:ec.a{*}", "ec.b": "sum:ec.b{*}"}
    configured = {"ec.a": "avg:ec.a{env:prod}"}
    merged = merged_metric_queries(extracted, configured)
    assert merged == {"ec.a": "avg:ec.a{env:prod}", "ec.b": "sum:ec.b{*}"}


def test_merge_empty_yields_none_for_adapter_defaults():
    assert merged_metric_queries(None, None) is None
    assert merged_metric_queries({}, {}) is None
