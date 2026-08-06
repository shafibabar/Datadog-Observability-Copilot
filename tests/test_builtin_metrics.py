"""Spec for the built-in EC metric registry (app/telemetry/builtin.py).

The 633 metric names this org actually emits are committed to the repo, so the
copilot has a real registry to query with no live-discovery call at all. That
matters twice over: discovery is one more thing that can fail on a corporate
network (a TLS-inspection proxy silently emptied the registry once), and a demo
must not depend on it succeeding.

The names are authority-grade — they were read off the live org — unlike the
knowledge JSONs, which propose. Written test-first (TDD red).
"""
from app.telemetry.builtin import (
    BUILTIN_METRIC_NAMES,
    builtin_queries,
    default_query,
    load_metric_names,
)

FUNNEL = "ec.centralised_audit.conduct.ingested.count"
LATENCY = "ec.alerting_service.enrichment_latency"


# --- loading -----------------------------------------------------------------


def test_ships_the_full_committed_name_list():
    assert len(BUILTIN_METRIC_NAMES) > 600
    assert FUNNEL in BUILTIN_METRIC_NAMES
    assert LATENCY in BUILTIN_METRIC_NAMES


def test_every_shipped_name_is_in_the_ec_namespace():
    assert all(n.startswith("ec.") for n in BUILTIN_METRIC_NAMES)


def test_names_are_sorted_and_deduplicated():
    assert list(BUILTIN_METRIC_NAMES) == sorted(set(BUILTIN_METRIC_NAMES))


def test_a_missing_file_yields_no_names_rather_than_raising(tmp_path):
    # Same contract as the knowledge loader: this layer never breaks startup.
    assert load_metric_names(tmp_path / "nope.txt") == ()


def test_blank_lines_and_comments_are_ignored(tmp_path):
    path = tmp_path / "names.txt"
    path.write_text("# a comment\n\nec.svc.one\n  ec.svc.two  \nec.svc.one\n", encoding="utf-8")
    assert load_metric_names(path) == ("ec.svc.one", "ec.svc.two")


# --- default aggregation -----------------------------------------------------
# A live-discovered name arrives with no aggregation, and the generic `avg:` is
# actively wrong for a counter: averaging per-interval increments answers a
# question nobody asked. The name shape says which one it is.


def test_a_count_metric_is_summed_as_a_count():
    assert default_query(FUNNEL) == f"sum:{FUNNEL}{{*}}.as_count()"
    assert default_query("ec.svc.alert_published_counter") == (
        "sum:ec.svc.alert_published_counter{*}.as_count()")


def test_a_rate_metric_is_summed_as_a_rate():
    metric = "ec.indexer.ingested_communication_consumption_rate"
    assert default_query(metric) == f"sum:{metric}{{*}}.as_rate()"


def test_a_latency_metric_is_averaged():
    assert default_query(LATENCY) == f"avg:{LATENCY}{{*}}"


def test_an_unrecognized_shape_falls_back_to_avg():
    assert default_query("ec.svc.something") == "avg:ec.svc.something{*}"


# --- the registry ------------------------------------------------------------


def test_builtin_queries_scopes_every_query_to_a_rewritable_brace():
    # LiveDatadogAdapter._apply_scope rewrites the FIRST {...} block from the
    # Scope; a query without one would silently ignore the env/tenant selection.
    assert all("{*}" in q for q in builtin_queries().values())


def test_builtin_queries_never_groups_by_a_tag():
    # get_metric reads series[0] only, so `by {tenant}` would answer for one
    # arbitrary tenant while looking like a platform-wide number.
    assert not any(" by {" in q for q in builtin_queries().values())


def test_builtin_queries_accepts_an_explicit_subset():
    assert builtin_queries([FUNNEL]) == {FUNNEL: f"sum:{FUNNEL}{{*}}.as_count()"}


# --- what the registry contains ----------------------------------------------
# The registry is the queryable set, so Datadog's generated sub-metrics are
# already excluded — the resolver's 8 picks must be 8 different signals, not
# five views of one. BUILTIN_METRIC_NAMES stays the FULL list, because it is the
# name universe that tells a generated `.count` from a real one.


def test_the_conduct_funnel_counters_are_in_the_registry():
    # The regression this registry exists to serve: these 36 real counters end in
    # `.count` and were being deleted as if Datadog had generated them.
    queries = builtin_queries()
    funnel = [n for n in queries if ".conduct." in n and n.endswith(".count")]
    assert len(funnel) >= 30
    assert FUNNEL in queries


def test_generated_sub_metrics_are_excluded_from_the_registry():
    queries = builtin_queries()
    assert f"{LATENCY}.max" not in queries
    assert f"{LATENCY}.count" not in queries
    assert LATENCY in queries
    # ~225 distinct signals out of 633 raw names.
    assert 150 < len(queries) < 300
    assert len(BUILTIN_METRIC_NAMES) > len(queries)


def test_a_namespace_filter_over_the_registry_keeps_the_funnel():
    # The same rule applied downstream in merged_metric_queries must agree.
    from app.telemetry.namespaces import filter_queries, parse_patterns

    out = filter_queries(
        builtin_queries(), parse_patterns("ec.*"), known=BUILTIN_METRIC_NAMES)
    assert FUNNEL in out
    assert set(out) == set(builtin_queries())
