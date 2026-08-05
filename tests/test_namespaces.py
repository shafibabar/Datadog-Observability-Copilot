"""Spec for metric-namespace scoping (DATADOG_METRIC_NAMESPACES).

A comma-separated list of glob patterns ("ec.*, ea.*") declares which metric
names are in scope at all. Pure and offline: no HTTP, no config, no I/O.
Written test-first (TDD red) before the implementation exists.
"""
from app.telemetry.namespaces import (
    filter_queries,
    is_stat_submetric,
    matches,
    parse_patterns,
    prefixes,
)

# --- parse_patterns ----------------------------------------------------------


def test_parses_comma_separated_globs_and_strips_spaces():
    assert parse_patterns("ec.*, ea.*") == ("ec.*", "ea.*")


def test_bare_prefix_without_a_wildcard_becomes_a_prefix_glob():
    # "ec." is the natural thing to type; treat it as "everything under ec.".
    assert parse_patterns("ec.,ea.") == ("ec.*", "ea.*")


def test_a_bare_namespace_without_the_dot_still_scopes_the_namespace():
    assert parse_patterns("ec") == ("ec.*",)


def test_empty_and_blank_input_yields_no_patterns():
    assert parse_patterns("") == ()
    assert parse_patterns("  ,  ,") == ()


def test_an_explicit_glob_is_left_exactly_as_written():
    # A narrower pattern must survive untouched — we never widen what was typed.
    assert parse_patterns("ec.quota_*") == ("ec.quota_*",)


def test_accepts_an_already_parsed_sequence():
    # Settings hands over a tuple (parsed by _get_list); normalize it the same way.
    assert parse_patterns(("ec.", "ea.*")) == ("ec.*", "ea.*")


# --- matches -----------------------------------------------------------------


def test_matches_names_under_a_configured_namespace():
    p = parse_patterns("ec.*, ea.*")
    assert matches("ec.quota_manager.pipeline_processed_counter", p)
    assert matches("ea.foo.bar", p)


def test_rejects_names_outside_every_namespace():
    p = parse_patterns("ec.*, ea.*")
    assert not matches("system.cpu.user", p)
    assert not matches("trace.http.request.duration", p)
    # A namespace must match on the dotted boundary, not any leading substring.
    assert not matches("economy.metric", p)


def test_no_patterns_matches_everything():
    # Unset config must preserve today's behavior exactly (no filtering at all).
    assert matches("system.cpu.user", ())
    assert matches("ec.anything", ())


def test_matching_is_case_insensitive():
    assert matches("EC.Quota_Manager.Count", parse_patterns("ec.*"))


# --- prefixes (feeds the Terraform extractor's regex) ------------------------


def test_prefixes_extracts_the_literal_head_of_each_pattern():
    assert prefixes(parse_patterns("ec.*, ea.*")) == ("ec.", "ea.")


def test_prefixes_of_a_narrow_glob_keeps_the_literal_part():
    assert prefixes(parse_patterns("ec.quota_*")) == ("ec.quota_",)


def test_prefixes_of_no_patterns_is_empty():
    assert prefixes(()) == ()


# --- filter_queries ----------------------------------------------------------


def test_filters_a_registry_down_to_the_configured_namespaces():
    processed = "ec.quota_manager.processed_counter"
    registry = {
        processed: f"sum:{processed}{{*}}.as_count()",
        "ea.review.latency": "avg:ea.review.latency{*}",
        "system.cpu.user": "avg:system.cpu.user{*}",
    }
    out = filter_queries(registry, parse_patterns("ec.*, ea.*"))
    assert set(out) == {processed, "ea.review.latency"}
    # Surviving queries are passed through untouched (aggregation preserved).
    assert out[processed] == f"sum:{processed}{{*}}.as_count()"


def test_explicitly_kept_names_bypass_the_filter():
    # DATADOG_METRIC_QUERIES is a deliberate override: if you named it yourself,
    # it stays in scope even when it doesn't match a namespace.
    registry = {"system.cpu.user": "avg:system.cpu.user{*}", "other.m": "avg:other.m{*}"}
    out = filter_queries(registry, parse_patterns("ec.*"), keep=("system.cpu.user",))
    assert set(out) == {"system.cpu.user"}


def test_no_patterns_leaves_the_registry_untouched():
    registry = {"system.cpu.user": "avg:system.cpu.user{*}"}
    assert filter_queries(registry, ()) == registry


def test_filtering_an_empty_registry_is_empty():
    assert filter_queries({}, parse_patterns("ec.*")) == {}


# --- statistical sub-metrics -------------------------------------------------
# Datadog auto-generates .count/.sum/.min/.max/… per distribution, so one logical
# metric appears as several names (1297 in-scope names on the real org vs ~500
# distinct signals). Keeping them would let the resolver spend its 8 picks on
# variants of a single metric instead of 8 different signals.


def test_recognizes_datadog_statistical_sub_metrics():
    base = "ec.alerting_service.alert_outbox_event_processing_time"
    for suffix in (".count", ".sum", ".min", ".max", ".avg", ".median", ".95percentile"):
        assert is_stat_submetric(base + suffix), suffix


def test_a_base_metric_is_not_a_sub_metric():
    assert not is_stat_submetric("ec.alerting_service.alert_outbox_event_processing_time")
    assert not is_stat_submetric("ec.alerting_service.alert_published_counter")


def test_a_name_that_merely_contains_a_suffix_word_is_kept():
    # "…count_total" / "…max_depth" are real metric names, not generated stats.
    assert not is_stat_submetric("ec.quota_manager.counter")
    assert not is_stat_submetric("ec.quota_manager.max_depth")


def test_filter_drops_statistical_sub_metrics():
    base = "ec.svc.processing_time"
    registry = {
        base: f"avg:{base}{{*}}",
        f"{base}.count": f"avg:{base}.count{{*}}",
        f"{base}.max": f"avg:{base}.max{{*}}",
        "ec.svc.published_counter": "avg:ec.svc.published_counter{*}",
    }
    out = filter_queries(registry, parse_patterns("ec.*"))
    assert set(out) == {base, "ec.svc.published_counter"}


def test_explicitly_kept_names_may_be_sub_metrics():
    # If you asked for a .95percentile by name, you get it.
    registry = {"ec.svc.latency.95percentile": "avg:ec.svc.latency.95percentile{*}"}
    out = filter_queries(registry, parse_patterns("ec.*"), keep=registry)
    assert out == registry


def test_sub_metrics_are_untouched_when_no_namespaces_are_configured():
    # Unset config still means "change nothing" — the whole contract of blank.
    registry = {"ec.svc.latency.count": "avg:ec.svc.latency.count{*}"}
    assert filter_queries(registry, ()) == registry
