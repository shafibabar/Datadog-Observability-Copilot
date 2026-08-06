"""Metric-namespace scoping — which metric names are in scope at all.

One config value (`DATADOG_METRIC_NAMESPACES`, e.g. "ec.*, ea.*") declares the
metric namespaces the copilot may look at. It is an **allowlist**: anything
discovered from Datadog or extracted from Terraform must match one of the
patterns, so a large org's thousands of metrics narrow to the platform we're
actually investigating. An empty list means "no filtering" so an unconfigured
install behaves exactly as before.

Pure and dependency-free (stdlib `fnmatch`): no HTTP, no config import, no I/O.
"""
from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Iterable


def parse_patterns(raw: str | Iterable[str]) -> tuple[str, ...]:
    """Normalize a raw namespace setting into glob patterns.

    Accepts a comma-separated string ("ec.*, ea.*") or an already-split sequence
    (what `Settings._get_list` produces). A value with no wildcard is the natural
    thing to type ("ec." or "ec") and means "everything under that namespace", so
    it becomes a prefix glob. An explicit glob is never widened.
    """
    items = raw.split(",") if isinstance(raw, str) else raw
    out: list[str] = []
    for item in items:
        pattern = (item or "").strip().lower()
        if not pattern:
            continue
        if "*" not in pattern and "?" not in pattern:
            # "ec" and "ec." both mean the ec namespace -> "ec.*"
            pattern = pattern.rstrip(".") + ".*"
        out.append(pattern)
    return tuple(out)


def matches(name: str, patterns: tuple[str, ...]) -> bool:
    """True when `name` is in scope. No patterns => everything is in scope."""
    if not patterns:
        return True
    lowered = (name or "").lower()
    return any(fnmatchcase(lowered, p) for p in patterns)


#: Datadog auto-generates one of these per distribution/histogram metric, so a
#: single logical signal appears under several names (verified live 2026-08-05:
#: 1297 in-scope `ec.*` names for roughly 500 distinct signals). They are excluded
#: from the registry so the resolver's top-K spends its slots on different metrics
#: rather than five views of one — the base metric stays fully queryable with any
#: aggregation. Matched as dotted suffixes, so a real name like
#: `ec.quota_manager.counter` or `…max_depth` is never mistaken for one.
_STAT_SUFFIXES = (
    ".count", ".sum", ".min", ".max", ".avg", ".median",
    ".50percentile", ".75percentile", ".90percentile", ".95percentile", ".99percentile",
)


def is_stat_submetric(name: str, known: Iterable[str] = ()) -> bool:
    """True for a Datadog-generated statistical sub-metric (`….processing_time.max`).

    The suffix alone is not proof, and getting this wrong is expensive in one
    specific direction: EC's business-volume counters are genuinely named
    `ec.centralised_audit.conduct.ingested.count` — 36 of them, the entire
    surveillance funnel, and the single most valuable evidence for "how many
    messages were ingested / qualified / sampled today". The suffix rule deleted
    every one of them from the registry.

    Given `known` — the full set of names the org actually emits — the two cases
    separate exactly: Datadog generates `X.count` only *alongside* its base
    metric `X`, so a suffixed name whose base is absent is a real metric. Pass
    the widest name universe available, not the registry being filtered: a
    bounded selection may not contain the base that proves the sibling generated.

    With no `known` set the old suffix-only rule applies unchanged, so callers
    that have no name universe keep their previous behaviour.
    """
    lowered = (name or "").lower()
    if not lowered.endswith(_STAT_SUFFIXES):
        return False
    universe = {n.lower() for n in known}
    if not universe:
        return True
    return lowered.rsplit(".", 1)[0] in universe


def prefixes(patterns: tuple[str, ...]) -> tuple[str, ...]:
    """The literal head of each pattern, up to its first wildcard.

    The Terraform extractor scans for metric names with a regex rather than
    globbing a list, so it needs the literal prefixes ("ec.", "ea.") to build its
    alternation from.
    """
    out: list[str] = []
    for pattern in patterns:
        head = pattern.split("*", 1)[0].split("?", 1)[0]
        if head:
            out.append(head)
    return tuple(out)


def filter_queries(
    registry: dict[str, str],
    patterns: tuple[str, ...],
    keep: Iterable[str] = (),
    known: Iterable[str] = (),
) -> dict[str, str]:
    """Narrow a {metric_name: query} registry to the configured namespaces, also
    dropping Datadog's generated statistical sub-metrics.

    `keep` names bypass both rules — that's the DATADOG_METRIC_QUERIES escape
    hatch: a metric you named explicitly stays in scope even outside the
    namespaces, and even if it's a `.95percentile`. Queries themselves are passed
    through untouched so the real aggregation (`sum:` / `.as_count()`) survives.

    `known` is the set of names the org emits, used to tell a generated
    sub-metric from a real one that happens to end in `.count` (see
    `is_stat_submetric`). Omitted, the suffix-only rule applies as before.

    With no patterns the registry is returned unchanged — blank config must mean
    "change nothing".
    """
    if not patterns:
        return dict(registry)
    kept = set(keep)
    universe = set(known)
    return {
        name: query for name, query in registry.items()
        if name in kept
        or (matches(name, patterns) and not is_stat_submetric(name, universe))
    }
