"""The built-in EC metric registry — the names this org actually emits.

`data/ec_metric_names.txt` is the metric list read off the live Datadog org and
committed to the repo. It exists so the copilot always has a real registry to
query, without depending on a live `GET /api/v1/metrics` call succeeding: that
call is best-effort by design, and on a corporate network behind a TLS-inspection
proxy it has already failed silently once, leaving an empty registry and a
copilot with nothing to look at.

This is **authority-grade**, unlike `app/knowledge/`. Those files *propose*
metrics and are partly self-declared "inferred"; this file is an observation of
what the org emits. It still composes with live discovery rather than replacing
it — a metric added since the snapshot is picked up by discovery, and this list
covers the case where discovery returns nothing.

Stdlib only; no HTTP, no config, no dependency on the adapter.
"""
from __future__ import annotations

from pathlib import Path

from app.telemetry.namespaces import is_stat_submetric

#: The committed snapshot of every metric name the org emits.
DATA_PATH = Path(__file__).parent / "data" / "ec_metric_names.txt"


def load_metric_names(path: Path | str | None = None) -> tuple[str, ...]:
    """Read metric names, one per line. Blank lines and `#` comments are skipped;
    the result is sorted and deduplicated.

    Never raises: a missing or unreadable file yields no names, and the caller
    falls back to live discovery exactly as it did before this module existed.
    """
    target = Path(path) if path is not None else DATA_PATH
    try:
        raw = target.read_text(encoding="utf-8-sig")
    except OSError:
        return ()
    names = {
        line.strip() for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    return tuple(sorted(names))


BUILTIN_METRIC_NAMES: tuple[str, ...] = load_metric_names()


# A metric name carries its own shape, and the generic `avg:` is actively wrong
# for a counter: averaging per-interval increments answers a question nobody
# asked ("how many messages were ingested today?" is a total, not a mean). These
# are defaults only — a question-catalog entry or DATADOG_METRIC_QUERIES supplies
# the exact aggregation where one is known.
_COUNT_SUFFIXES = (".count", "_counter", "_count", ".flag")
_RATE_SUFFIXES = ("_rate",)


def default_query(name: str) -> str:
    """The Datadog query for a metric name with no configured aggregation.

    Always scoped `{*}` and never grouped `by {...}`: the adapter rewrites the
    first brace block from the investigation Scope, and reads only the first
    series returned, so a grouped query would silently answer for one tag value.
    """
    lowered = (name or "").lower()
    if lowered.endswith(_RATE_SUFFIXES):
        return f"sum:{name}{{*}}.as_rate()"
    if lowered.endswith(_COUNT_SUFFIXES):
        return f"sum:{name}{{*}}.as_count()"
    return f"avg:{name}{{*}}"


def builtin_queries(names=None) -> dict[str, str]:
    """The adapter-ready {name: query} registry for the built-in names.

    Datadog's generated statistical sub-metrics are excluded: the registry is the
    set the resolver picks its top-8 from, and those eight must be eight
    different signals rather than five views of one distribution. The real
    `…conduct.ingested.count` counters are kept — `is_stat_submetric` separates
    them using the full name list as its universe. `BUILTIN_METRIC_NAMES` remains
    that complete list, because it is what makes the distinction possible.

    An explicit `names` argument is taken as given, no filtering applied.
    """
    if names is not None:
        return {n: default_query(n) for n in names}
    return {
        n: default_query(n) for n in BUILTIN_METRIC_NAMES
        if not is_stat_submetric(n, BUILTIN_METRIC_NAMES)
    }
