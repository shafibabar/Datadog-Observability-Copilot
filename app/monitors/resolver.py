"""Relevance resolver — maps user vocabulary to the metrics worth querying.

The Terraform repo yields hundreds of metric queries; querying them all per
question is impossible (HTTP volume, rate limits, token cost). This module
deterministically selects the top-K metrics relevant to the current question
(and recent history), using the alias vocabulary extracted alongside them.
Deterministic on purpose: explainable, offline-testable, no extra LLM call.
"""
from __future__ import annotations

import re

from app.monitors.index import MonitorsIndex, aliases_from_metric_names

#: How many metrics one investigation may query. Bounds HTTP calls and tokens.
DEFAULT_TOP_K = 8

#: Weight for the EC knowledge layer's top candidate. Above the alias-phrase
#: weight (10.0) because a knowledge hit is a *semantic* match — it knows
#: "sampler" means the quota manager — whereas an alias hit is a string match on
#: a Terraform module name. Later candidates decay so the knowledge layer's own
#: ordering survives, with a floor that still clears token-overlap noise.
KNOWLEDGE_WEIGHT = 12.0
KNOWLEDGE_FLOOR = 5.0

#: Weight for a metric named by a matched question-catalog entry. Above the
#: knowledge layer's, because this is not an inference about which service the
#: question concerns — it is a recorded statement that THIS series answers THIS
#: question, with the aggregation to use. Nothing else in the resolver knows
#: that. Later metrics in the entry decay only slightly: an entry that names
#: five funnel stages means all five, not a favourite.
CATALOG_WEIGHT = 30.0
CATALOG_DECAY = 0.5

_WORD_RE = re.compile(r"[a-z0-9]+")

# Generic metric-name segments that shouldn't count as term matches on their own
# ("error" would otherwise match nearly every counter for any error question).
_WEAK_SEGMENTS = {"ec", "count", "counter", "rate", "total", "event", "events"}


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def select_metrics(
    question: str,
    history: list[tuple[str, str]] | None,
    index: MonitorsIndex,
    available: set[str],
    k: int = DEFAULT_TOP_K,
    vocabulary=None,
    catalog=(),
) -> list[str]:
    """Select up to `k` metric names relevant to the question.

    Scoring: a matched question-catalog entry outranks everything, because it is
    a recorded answer to this exact question rather than an inference about it.
    Below that, the EC knowledge layer's candidates rank next when a
    `vocabulary` is supplied — it is the only source that maps everyday words
    ("sampler", "are we backed up?") onto services and monitors. Below that, an
    alias phrase appearing in the question is a strong signal for all its
    metrics (recent-history matches count at reduced weight); question tokens
    overlapping a metric's own name segments add a weaker signal. With no signal
    at all, fall back to a golden set (one throughput-ish + one error-ish metric
    per service) so "is everything healthy?" still gets real telemetry. Only
    metrics in `available` are ever returned.

    `vocabulary` and `catalog` are optional and purely additive: omitted, this
    behaves exactly as it did before those layers existed.

    `available` — the registry the data source can actually query — is the
    authority on what exists, NOT `index.metric_queries`. The Terraform repo is an
    optional source of richer vocabulary (module phrases like "message
    processing"), but live discovery alone routinely produces hundreds of metrics
    with no Terraform checkout at all; keying off the index would then select
    nothing and leave the caller to query everything.
    """
    if not available:
        return []

    question_text = (question or "").lower()
    history_text = " ".join(
        content for _, content in (history or [])[-4:]
    ).lower()
    question_tokens = _tokens(question_text)

    scores: dict[str, float] = {}

    # A catalog hit is the strongest signal available: someone recorded that
    # these exact series answer this exact question. Only its live metrics are
    # returned — `match_question` has already dropped the ones this org's
    # registry does not carry.
    for rank, metric in enumerate(catalog_metrics(question, catalog, available)):
        scores[metric] = scores.get(metric, 0.0) + CATALOG_WEIGHT - rank * CATALOG_DECAY

    # EC knowledge next: it resolves user words to services, monitors and
    # lifecycle stages that no string match can reach. Its own ordering is
    # meaningful (monitor-named series lead), so weight decays down the list.
    for rank, metric in enumerate(_knowledge_candidates(question, vocabulary, available)):
        scores[metric] = scores.get(metric, 0.0) + max(
            KNOWLEDGE_WEIGHT - rank, KNOWLEDGE_FLOOR)

    # Terraform module vocabulary first, then phrases implied by the available
    # metric names themselves (the only vocabulary when there's no Terraform repo).
    aliases: dict[str, list[str]] = {
        alias: list(metrics) for alias, metrics in index.aliases.items()}
    for alias, metrics in aliases_from_metric_names(available).items():
        aliases.setdefault(alias, []).extend(metrics)

    for alias, metrics in aliases.items():
        weight = 0.0
        if alias in question_text:
            weight = 10.0
        elif alias in history_text:
            weight = 4.0  # follow-ups: "and the errors?" after a service question
        if weight:
            for metric in metrics:
                scores[metric] = scores.get(metric, 0.0) + weight

    for metric in available:
        segments = _tokens(metric.replace(".", " ").replace("_", " ")) - _WEAK_SEGMENTS
        overlap = len(segments & question_tokens)
        if overlap:
            scores[metric] = scores.get(metric, 0.0) + overlap

    ranked = [
        m for m, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        if m in available
    ]
    if ranked:
        return ranked[:k]
    return _golden_set(available, k)


def catalog_metrics(question: str, catalog, available: set[str]) -> list[str]:
    """The live metrics a matched question-catalog entry names, best first.

    Imported lazily and defended the same way as the knowledge layer: a catalog
    problem must degrade selection, never break it.
    """
    if not catalog or not available:
        return []
    try:
        from app.knowledge.questions import match_question

        hit = match_question(question, tuple(catalog), available)
        return list(hit.metrics) if hit else []
    except Exception:  # pragma: no cover - defensive; the catalog is optional
        return []


def _knowledge_candidates(question: str, vocabulary, available: set[str]) -> list[str]:
    """Metrics the EC knowledge layer proposes for this question, best first.

    Imported lazily so the resolver keeps working — and the correlation tests
    keep running — with no knowledge package present. Returns [] on anything
    unexpected: a vocabulary problem must degrade selection, never break it.
    """
    if vocabulary is None or not available:
        return []
    try:
        from app.knowledge.interpret import candidate_metrics, interpret

        return candidate_metrics(interpret(question, vocabulary), vocabulary, available)
    except Exception:  # pragma: no cover - defensive; knowledge is optional
        return []


def _golden_set(available: set[str], k: int) -> list[str]:
    """One throughput-flavored and one error-flavored metric per service, capped
    at k — the default lens when the question names nothing specific."""
    by_service: dict[str, list[str]] = {}
    for metric in sorted(available):
        parts = metric.split(".")
        if len(parts) >= 2:
            by_service.setdefault(parts[1], []).append(metric)

    selected: list[str] = []
    for service, metrics in sorted(by_service.items()):
        throughput = [m for m in metrics if "rate" in m or "processed" in m or "consumption" in m]
        errors = [m for m in metrics if "error" in m or "dlt" in m or "failed" in m]
        for bucket in (throughput, errors):
            if bucket and len(selected) < k:
                selected.append(bucket[0])
    return selected[:k]
