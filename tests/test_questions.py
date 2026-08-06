"""Spec for the answerable-question catalog (app/knowledge/questions.py).

`data/questions.json` pairs the natural-language questions a non-technical user
asks with the exact Datadog query that answers each one. It turns a vague
question into a named intent, a bounded set of metrics and a stated answer
shape — so the model interprets telemetry rather than guessing which telemetry
to look at.

It is a HINT LAYER: the file names 60+ metrics, and only some of them are
actually emitted by this org (checked against the committed registry: several
`_error_counter` and `_api_latency` series in it do not exist). A catalog entry
may propose; only the live registry decides. Written test-first (TDD red).
"""
import pytest

from app.knowledge.questions import (
    QuestionEntry,
    load_question_catalog,
    match_question,
    match_unanswerable,
    metrics_in,
    query_for,
)

FUNNEL = "ec.centralised_audit.conduct.ingested.count"
QUALIFIED = "ec.centralised_audit.conduct.qualified.count"
NOT_QUALIFIED = "ec.centralised_audit.conduct.not_qualified.count"


@pytest.fixture(scope="module")
def catalog():
    return load_question_catalog()


@pytest.fixture(scope="module")
def available():
    from app.telemetry.builtin import builtin_queries

    return set(builtin_queries())


# --- loading -----------------------------------------------------------------


def test_loads_the_shipped_catalog(catalog):
    assert len(catalog) > 30
    assert all(isinstance(e, QuestionEntry) for e in catalog)
    assert all(e.id and e.question for e in catalog)


def test_a_missing_or_broken_file_yields_an_empty_catalog(tmp_path):
    # Same contract as the rest of app/knowledge: degrade, never raise.
    assert load_question_catalog(tmp_path / "absent.json") == ()
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_question_catalog(broken) == ()
    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text('["a list"]', encoding="utf-8")
    assert load_question_catalog(wrong_shape) == ()


def test_entries_carry_their_intent_and_answer_shape(catalog):
    entry = next(e for e in catalog if e.id == "STG-001")
    assert entry.intent == "COUNT_STAGE"
    assert "integer" in entry.answer_shape
    assert entry.service == "ec-centralised-audit"


# --- pulling metrics out of a resolvedQuery ----------------------------------


def test_extracts_a_metric_from_a_simple_query():
    assert metrics_in(f"sum:{FUNNEL}{{tenant:msprod}}.as_count()") == (FUNNEL,)


def test_extracts_every_metric_from_a_compound_query():
    q = (f"sum:{QUALIFIED}{{*}}.as_count() / (sum:{QUALIFIED}{{*}}.as_count() + "
         f"sum:{NOT_QUALIFIED}{{*}}.as_count())")
    assert metrics_in(q) == (QUALIFIED, NOT_QUALIFIED)


def test_extracts_metrics_written_as_prose_under_a_named_group():
    # STG-010 and ERR-005 describe their series in words rather than as queries:
    # "sum by stage of: conduct.ingested.count, conduct.qualified.count … (all
    # under ec.centralised_audit)". Those are real metrics and must not be lost.
    q = ("sum by stage of: conduct.ingested.count, conduct.qualified.count "
         "(all under ec.centralised_audit)")
    assert metrics_in(q) == (FUNNEL, QUALIFIED)


def test_a_bare_namespace_mention_is_not_a_metric():
    assert metrics_in("something about ec.centralised_audit generally") == ()


# --- building a queryable Datadog query --------------------------------------


def test_keeps_the_stated_aggregation_and_count_modifier():
    assert query_for(FUNNEL, f"sum:{FUNNEL}{{tenant:msprod}}.as_count()") == (
        f"sum:{FUNNEL}{{*}}.as_count()")


def test_keeps_a_percentile_aggregation():
    latency = "ec.indexer.ingested_communication_event_latency"
    assert query_for(latency, f"p95:{latency}{{*}} by {{tenant}}") == f"p95:{latency}{{*}}"


def test_resets_the_scope_so_the_investigation_scope_can_be_applied():
    # The adapter rewrites the FIRST {...} block from the Scope; a hardcoded
    # tenant in the catalog would fight the user's @ selection.
    assert "{*}" in query_for(FUNNEL, f"sum:{FUNNEL}{{tenant:msprod}}.as_count()")


def test_strips_group_by_because_only_the_first_series_is_read():
    q = query_for(FUNNEL, f"sum:{FUNNEL}{{*}} by {{tenant,pipeline_name}}.as_count()")
    assert q == f"sum:{FUNNEL}{{*}}.as_count()"
    assert " by {" not in q


def test_unwraps_a_top_function():
    filtered = "ec.centralised_audit.conduct.queue.v3.filtered.count"
    q = query_for(filtered, f"top(sum:{filtered}{{*}} by {{pipeline_name}}.as_count(), 10, 'sum', 'desc')")
    assert q == f"sum:{filtered}{{*}}.as_count()"


def test_falls_back_to_the_name_shaped_default_when_no_aggregation_is_stated():
    # ERR-005's prose names metrics with no `sum:` prefix attached to them.
    from app.telemetry.builtin import default_query

    assert query_for(FUNNEL, "sum of the conduct.ingested.count series") == default_query(FUNNEL)


# --- live vs proposed --------------------------------------------------------


def test_entry_metrics_are_split_into_live_and_not_emitted(catalog, available):
    # ERR-003 names two `_error_counter` series this org does not emit.
    entry = next(e for e in catalog if e.id == "ERR-003")
    assert entry.live_metrics(available) == ()
    assert "ec.quota_manager.kpi_event_consumer_error_counter" in entry.missing_metrics(available)


def test_a_fully_live_entry_reports_no_gap(catalog, available):
    entry = next(e for e in catalog if e.id == "STG-001")
    assert entry.live_metrics(available) == (FUNNEL,)
    assert entry.missing_metrics(available) == ()


def test_the_funnel_question_resolves_all_five_stages(catalog, available):
    # STG-010 is the flagship demo question; every stage counter must be live.
    entry = next(e for e in catalog if e.id == "STG-010")
    assert len(entry.live_metrics(available)) >= 5
    assert FUNNEL in entry.live_metrics(available)


def test_a_useful_share_of_the_catalog_is_actually_answerable(catalog, available):
    answerable = [e for e in catalog if e.live_metrics(available)]
    assert len(answerable) >= 15


# --- matching a user's question ----------------------------------------------


def test_matches_the_verbatim_question(catalog, available):
    hit = match_question(
        "How many communications were ingested today for Morgan Stanley?",
        catalog, available)
    assert hit.entry.id == "STG-001"
    assert hit.metrics == (FUNNEL,)


def test_matches_a_paraphrase(catalog, available):
    hit = match_question("how many messages did we ingest yesterday?", catalog, available)
    assert hit is not None
    assert FUNNEL in hit.metrics


def test_message_and_communication_are_the_same_word(catalog, available):
    # The platform's metrics say "communication"; every person asking says
    # "message". Both phrasings must reach the same entry.
    for phrasing in ("how many messages were ingested today?",
                     "how many communications were ingested today?"):
        assert match_question(phrasing, catalog, available).entry.id == "STG-001", phrasing


def test_a_latency_question_does_not_match_a_counting_one(catalog, available):
    # These two share nearly every content word and want opposite metrics.
    counted = match_question("how many messages did we ingest?", catalog, available)
    timed = match_question("how fast is the indexer ingesting messages?", catalog, available)
    assert counted.entry.intent in ("COUNT_STAGE", "THROUGHPUT", "RECON")
    assert timed.entry.intent == "LATENCY"


def test_matches_the_funnel_breakdown_question(catalog, available):
    hit = match_question("break down the whole funnel by stage for last 24h", catalog, available)
    assert hit.entry.id == "STG-010"


def test_an_unrelated_question_matches_nothing(catalog, available):
    assert match_question("what is the capital of France?", catalog, available) is None
    assert match_question("", catalog, available) is None


def test_every_catalog_question_matches_itself_or_nothing(catalog, available):
    """The failure that matters is SUBSTITUTION, not a miss.

    A near-miss entry attaches a confident "these series answer it" block to
    series that answer a different question — e.g. "how slow is the alert-fetch
    API?" landing on the surveillance filter's fetch-policies latency because
    both say "slow" and "fetch". A miss just falls back to normal resolution.
    """
    for entry in catalog:
        hit = match_question(entry.question, catalog, available)
        assert hit is None or hit.entry.id == entry.id, (
            f"{entry.question!r} matched {hit.entry.id}, not {entry.id}")


def test_a_question_whose_own_series_are_dead_matches_nothing(catalog, available):
    # ERR-003, DLT-001, IDX-001 and API-002 all name series this org does not
    # emit. None of them may borrow another entry's series.
    for entry_id in ("ERR-003", "DLT-001", "IDX-001", "API-002"):
        entry = next(e for e in catalog if e.id == entry_id)
        assert match_question(entry.question, catalog, available) is None, entry_id


def test_an_error_question_never_lands_on_a_throughput_counter(catalog, available):
    # A consumption-rate counter is not a worse answer to "is it erroring?" —
    # it is a confident answer to a different question.
    hit = match_question("is the KPI consumer or publisher erroring?", catalog, available)
    assert hit is None or hit.entry.intent in ("ERROR_RATE", "DEADLETTER")


def test_a_question_about_one_service_never_answers_from_another(catalog, available):
    hit = match_question(
        "what's the pipeline execution report API response time?", catalog, available)
    assert hit is None or not any(
        m.startswith("ec.surveillance_filter.") for m in hit.metrics)


def test_never_matches_an_entry_whose_metrics_are_all_dead(catalog, available):
    # "Are there indexing errors?" is ERR-001, whose metric this org does not
    # emit. Returning it would put a query behind an answer that cannot run.
    hit = match_question("are there indexing errors?", catalog, available)
    assert hit is None or hit.entry.id != "ERR-001"


def test_a_match_only_ever_returns_metrics_in_the_registry(catalog, available):
    for question in (
        "how many were qualified vs not qualified?",
        "how slow is enrichment in alerting?",
        "what is the ingest throughput on the indexer?",
    ):
        hit = match_question(question, catalog, available)
        if hit is not None:
            assert set(hit.metrics) <= available, question


def test_an_empty_registry_matches_nothing(catalog):
    assert match_question("how many messages were ingested today?", catalog, set()) is None


def test_a_match_carries_the_queries_and_the_gap(catalog, available):
    hit = match_question("how many communications were ingested today?", catalog, available)
    assert hit.queries[FUNNEL] == f"sum:{FUNNEL}{{*}}.as_count()"
    assert hit.entry.intent == "COUNT_STAGE"


def test_matching_is_deterministic(catalog, available):
    question = "how many messages were surveilled?"
    first = match_question(question, catalog, available)
    assert all(match_question(question, catalog, available).entry.id == first.entry.id
               for _ in range(3))


# --- questions this platform cannot answer -----------------------------------
# Half the catalog names series this org does not emit. Those questions can't be
# answered — but they can be answered ABOUT, which is a real answer.


def test_a_known_but_unmeasured_question_is_identified_as_such(catalog, available):
    hit = match_unanswerable("are there indexing errors?", catalog, available)
    assert hit.entry.id == "ERR-001"
    assert hit.metrics == ()
    assert "ec.indexer.indexing_error_counter" in hit.missing


def test_an_answerable_question_is_not_reported_as_unanswerable(catalog, available):
    assert match_unanswerable(
        "how many communications were ingested today?", catalog, available) is None


def test_an_unrelated_question_is_not_reported_as_unanswerable(catalog, available):
    assert match_unanswerable("what is the capital of France?", catalog, available) is None


def test_the_unanswerable_block_refuses_substitution_explicitly(catalog, available):
    text = match_unanswerable("are there indexing errors?", catalog, available).describe()
    assert "UNANSWERABLE" in text
    assert "not emitted" in text.lower()
    assert "ec.indexer.indexing_error_counter" in text
    # It must carry no query, or the model could cite one that cannot run.
    assert "{*}" not in text


# --- the prompt block --------------------------------------------------------


def test_describe_names_the_intent_metrics_and_answer_shape(catalog, available):
    hit = match_question("how many communications were ingested today?", catalog, available)
    text = hit.describe()
    assert "COUNT_STAGE" in text
    assert FUNNEL in text
    assert "STG-001" in text


def test_describe_reports_metrics_the_platform_does_not_emit(catalog, available):
    # A partially-live entry must say so, or the model reports a total that
    # silently omits a whole leg of the comparison.
    entry = next(e for e in catalog if e.id == "ERR-003")
    entry_missing = entry.missing_metrics(available)
    assert entry_missing  # guards the fixture, not the feature
    from app.knowledge.questions import QuestionMatch

    text = QuestionMatch(entry=entry, metrics=(FUNNEL,), queries={}, missing=entry_missing).describe()
    assert "not emitted" in text.lower()
    assert entry_missing[0] in text
