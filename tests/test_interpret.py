"""Specs for the EC vocabulary, the question interpreter, and coverage gaps.

The interpreter is deterministic and offline by design: the same question always
resolves the same way, with no LLM call, so it is explainable and testable. The
binding rule throughout is the HINT-LAYER contract — the knowledge files may
propose metrics, but only the live registry (`available`) decides what exists.
Parts of those files are self-declared "inferred"/"not source-verified", and a
metric that cannot return data must never be citable as evidence.
"""
from __future__ import annotations

import pytest

from app.knowledge.gaps import detection_gaps
from app.knowledge.interpret import candidate_metrics, interpret
from app.knowledge.loader import load_knowledge
from app.knowledge.vocabulary import build_vocabulary

# A representative slice of a real registry. Deliberately does NOT contain every
# metric the knowledge files name — that asymmetry is what the hint-layer specs
# below exercise.
AVAILABLE = {
    "ec.indexer.ingested_communication_consumption_rate",
    "ec.indexer.ingested_communication_event_latency",
    "ec.indexer.indexing_error_counter",
    "ec.indexer.surveilled_communication_error_counter",
    "ec.quota_manager.metadata_comms_consumer_dlt_counter",
    "ec.quota_manager.sampling_stats_counter",
    "ec.quota_manager.pipeline_processed_counter",
    "ec.surveillance_filter.policy_api_latency",
    "ec.surveillance_filter.policy_evaluation_error_counter",
    "ec.centralised_audit.communication_event_dlt_counter",
    "ec.reporting.pending_pipelines_count",
}


@pytest.fixture(scope="module")
def kb():
    return load_knowledge()


@pytest.fixture(scope="module")
def vocab(kb):
    return build_vocabulary(kb)


# --- vocabulary ------------------------------------------------------------

def test_service_synonym_resolves_to_its_canonical_repo(vocab):
    meanings = vocab.lookup("sampler")
    assert any(
        m.kind == "service" and m.canonical == "ec-surveillance-quota-manager"
        for m in meanings
    )


def test_the_ui_word_queue_is_known_to_mean_the_backend_pipeline(vocab):
    meanings = vocab.lookup("queue")
    assert any(m.kind == "concept" and m.canonical == "pipeline" for m in meanings)


def test_metric_type_synonyms_are_registered(vocab):
    assert any(m.canonical == "latency" for m in vocab.lookup("how slow"))
    assert any(m.canonical == "infra_kafka_lag" for m in vocab.lookup("backed up"))
    assert any(m.canonical == "dlt_counter" for m in vocab.lookup("dead-lettered"))


def test_guard_phrases_are_usable_as_substring_vocabulary(vocab):
    phrases = vocab.guard_phrases()
    assert "quota manager" in phrases
    assert "policy evaluator" in phrases
    # A 1-2 character phrase matched as a substring would fast-allow everything.
    assert all(len(p) >= 4 for p in phrases)


def test_generic_domain_nouns_are_kept_out_of_guard_vocabulary(vocab):
    """The guard matches its vocabulary as substrings and fast-allows on a hit.
    "message", "record" and "status" are ordinary English — admitting them would
    fast-allow almost anything and undo the deliberate re-tightening of the
    Stage-1 list. Stage 2 owns that ambiguous middle."""
    phrases = vocab.guard_phrases()
    for generic in (
        "message", "record", "content", "people", "users", "group",
        "status", "count", "volume", "report", "action", "store",
    ):
        assert generic not in phrases, f"{generic!r} is too generic to fast-allow"


def test_multiword_platform_phrases_are_offered_to_the_guard(vocab):
    phrases = vocab.guard_phrases()
    assert "quota manager" in phrases
    assert "policy evaluator" in phrases
    assert "gateway board" in phrases


def test_single_word_service_names_are_still_offered(vocab):
    """A one-word phrase survives only when it names a service, monitor or
    dashboard — those are this platform's own nouns, not English."""
    assert "sampler" in vocab.guard_phrases()


def test_a_repo_resolves_to_metric_segments_that_actually_exist(vocab):
    # groupName is "(underscore-style; not read)" for this repo, so the segment
    # must be derived from the repo name and confirmed against the registry.
    segments = vocab.metric_segments("ec-surveillance-quota-manager", AVAILABLE)
    assert "quota_manager" in segments


def test_singular_plural_mismatch_between_repo_and_metric_name_is_bridged(vocab):
    # repo "ec-manual-runs-service" but the live metric segment is
    # "manual_run_service" (singular).
    available = {"ec.manual_run_service.lookback_completed_total"}
    segments = vocab.metric_segments("ec-manual-runs-service", available)
    assert "manual_run_service" in segments


# --- interpretation --------------------------------------------------------

def test_lag_question_resolves_service_and_intent(vocab):
    result = interpret("is the sampler backed up?", vocab)
    assert result.intent == "GET_LAG"
    assert "ec-surveillance-quota-manager" in result.services


def test_latency_question_defaults_to_p99(vocab):
    result = interpret("how slow is indexing?", vocab)
    assert result.intent == "GET_LATENCY"
    assert result.metric_type == "latency"
    assert result.percentile == "p99"


def test_an_explicit_percentile_beats_the_default(vocab):
    result = interpret("what's the p95 latency of indexing ingested comms?", vocab)
    assert result.percentile == "p95"


def test_throughput_question_resolves_service_and_time_range(vocab):
    result = interpret("how many messages did the indexer process today?", vocab)
    assert result.intent == "GET_THROUGHPUT"
    assert "ec-indexer" in result.services
    assert result.time_range == "1d"


def test_error_question_resolves_intent(vocab):
    result = interpret("what's failing in the filter?", vocab)
    assert result.intent == "GET_ERRORS"
    assert "ec-surveillance-filter" in result.services


def test_deadletter_question_resolves_intent(vocab):
    result = interpret("how many alerts got dead-lettered?", vocab)
    assert result.intent == "GET_DEADLETTER"


def test_week_time_range_is_recognised(vocab):
    result = interpret("how many reviewer groups were created this week?", vocab)
    assert result.time_range == "7d"


def test_the_pipeline_stage_of_a_resolved_service_is_attributed(vocab):
    result = interpret("how many messages did the indexer process today?", vocab)
    assert ("ec-indexer", 8, "indexed") in result.stages


def test_a_contraction_and_its_expansion_resolve_identically(vocab):
    """The files write "what's failing"; people type both forms."""
    assert interpret("what's failing in the filter?", vocab).intent == "GET_ERRORS"
    assert interpret("what is failing in the filter?", vocab).intent == "GET_ERRORS"


def test_a_multiword_phrase_tolerates_inflection_on_its_last_word(vocab):
    """The vocabulary says "dead-lettered"; "dead letter" is the same ask."""
    assert interpret("did the audit dead letter anything?", vocab).intent == "GET_DEADLETTER"
    assert interpret("how many were dead-lettered?", vocab).intent == "GET_DEADLETTER"


# --- monitors and dashboards as vocabulary ---------------------------------

def test_a_monitor_synonym_resolves_to_its_module(vocab):
    result = interpret("are the pipelines finishing on time?", vocab)
    assert "pipeline_not_completion_in_time" in result.monitors


def test_the_end_to_end_health_question_finds_the_only_end_to_end_monitor(vocab):
    result = interpret("is the whole pipeline healthy end to end?", vocab)
    assert "qualified_comms_failure_rate" in result.monitors


def test_a_dashboard_synonym_resolves_to_its_module(vocab):
    result = interpret("show me the gateway board", vocab)
    assert "ec_gateway_dashboard" in result.dashboards


def test_a_monitors_own_metric_becomes_a_candidate(vocab):
    result = interpret("are the pipelines finishing on time?", vocab)
    metrics = candidate_metrics(result, vocab, AVAILABLE)
    assert "ec.reporting.pending_pipelines_count" in metrics


def test_a_monitor_metric_absent_from_the_registry_is_not_returned(vocab):
    """debezium_connector_failure names a jmx.* metric this registry lacks."""
    result = interpret("did the debezium connector fail?", vocab)
    assert result.monitors
    assert candidate_metrics(result, vocab, AVAILABLE) == []


def test_monitor_phrases_are_offered_to_the_guard(vocab):
    assert "ingest spike" in vocab.guard_phrases()


def test_an_unrecognised_question_yields_an_empty_interpretation(vocab):
    result = interpret("qwertyuiop zxcvbnm", vocab)
    assert result.is_empty
    assert result.services == ()
    assert result.intent is None


def test_empty_and_none_questions_do_not_raise(vocab):
    assert interpret("", vocab).is_empty
    assert interpret(None, vocab).is_empty


def test_describe_names_the_resolved_terms_for_the_prompt(vocab):
    text = interpret("is the sampler backed up?", vocab).describe()
    assert "sampler" in text
    assert "ec-surveillance-quota-manager" in text
    assert "GET_LAG" in text


def test_describe_is_empty_when_nothing_resolved(vocab):
    assert interpret("qwertyuiop", vocab).describe() == ""


# --- candidate metrics: the hint-layer contract ----------------------------

def test_candidates_are_scoped_to_the_resolved_service(vocab):
    result = interpret("how many did the quota manager sample?", vocab)
    metrics = candidate_metrics(result, vocab, AVAILABLE)
    assert metrics
    assert all(m.startswith("ec.quota_manager.") for m in metrics)


def test_a_metric_named_in_the_knowledge_files_but_not_live_is_never_returned(vocab):
    """The files name ec.review_service.* metrics; this registry has none. The
    interpreter must not invent them — live discovery is the authority."""
    result = interpret("how many reviewer groups were created?", vocab)
    metrics = candidate_metrics(result, vocab, AVAILABLE)
    assert metrics == []


def test_metric_type_narrows_the_candidates(vocab):
    result = interpret("how slow is indexing?", vocab)
    metrics = candidate_metrics(result, vocab, AVAILABLE)
    assert "ec.indexer.ingested_communication_event_latency" in metrics
    assert "ec.indexer.indexing_error_counter" not in metrics


def test_error_type_selects_error_counters(vocab):
    result = interpret("how many errors is the indexer throwing?", vocab)
    metrics = candidate_metrics(result, vocab, AVAILABLE)
    assert "ec.indexer.indexing_error_counter" in metrics
    assert "ec.indexer.ingested_communication_event_latency" not in metrics


def test_an_empty_registry_yields_no_candidates(vocab):
    result = interpret("how slow is indexing?", vocab)
    assert candidate_metrics(result, vocab, set()) == []


def test_an_empty_interpretation_yields_no_candidates(vocab):
    result = interpret("qwertyuiop", vocab)
    assert candidate_metrics(result, vocab, AVAILABLE) == []


def test_candidates_are_deterministic(vocab):
    result = interpret("how many did the quota manager sample?", vocab)
    first = candidate_metrics(result, vocab, AVAILABLE)
    second = candidate_metrics(result, vocab, AVAILABLE)
    assert first == second


# --- coverage gaps ---------------------------------------------------------

def test_a_lag_question_surfaces_the_missing_monitor_gap(kb, vocab):
    gaps = detection_gaps("are we backed up anywhere?", kb, vocab)
    assert gaps
    gap = gaps[0]
    assert gap.kind == "no_monitor"
    assert "consumer_lag" in gap.reason or "lag" in gap.topic
    assert gap.check  # a dashboard to look at instead


def test_the_gap_names_a_specific_dashboard_when_one_is_documented(kb, vocab):
    """"dashboard only" is useless advice. The worked examples say exactly which
    widget group to open, so that wins when it exists."""
    gaps = detection_gaps("are we backed up anywhere?", kb, vocab)
    assert "kafka_lags" in gaps[0].check


def test_a_pod_health_question_surfaces_its_gap(kb, vocab):
    gaps = detection_gaps("is the quota manager pod crashing?", kb, vocab)
    assert any(g.kind == "no_monitor" for g in gaps)


def test_a_normally_covered_question_reports_no_gap(kb, vocab):
    assert detection_gaps("how slow is the policy api?", kb, vocab) == []


def test_gaps_degrade_gracefully_without_knowledge(vocab):
    from app.knowledge.loader import KnowledgeBase

    assert detection_gaps("are we backed up?", KnowledgeBase(), vocab) == []


def test_gap_text_is_renderable(kb, vocab):
    for gap in detection_gaps("are we backed up anywhere?", kb, vocab):
        assert gap.topic and gap.reason
        assert isinstance(gap.check, str)
