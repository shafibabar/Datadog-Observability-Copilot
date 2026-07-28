"""Relevance resolver — maps user vocabulary to the metrics worth querying.

The Terraform repo yields hundreds of metric queries; querying them all per
question is impossible (HTTP volume, rate limits, token cost). This module
deterministically selects the top-K metrics relevant to the current question
(and recent history), using the alias vocabulary extracted alongside them.
Deterministic on purpose: explainable, offline-testable, no extra LLM call.
"""
from __future__ import annotations

import re

from app.monitors.index import MonitorsIndex

#: How many metrics one investigation may query. Bounds HTTP calls and tokens.
DEFAULT_TOP_K = 8

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
) -> list[str]:
    """Select up to `k` metric names relevant to the question.

    Scoring: an alias phrase appearing in the question is a strong signal for
    all its metrics (recent-history matches count at reduced weight); question
    tokens overlapping a metric's own name segments add a weaker signal. With
    no signal at all, fall back to a golden set (one throughput-ish + one
    error-ish metric per service) so "is everything healthy?" still gets real
    telemetry. Only metrics in `available` are ever returned.
    """
    if not index.metric_queries:
        return []

    question_text = (question or "").lower()
    history_text = " ".join(
        content for _, content in (history or [])[-4:]
    ).lower()
    question_tokens = _tokens(question_text)

    scores: dict[str, float] = {}

    for alias, metrics in index.aliases.items():
        weight = 0.0
        if alias in question_text:
            weight = 10.0
        elif alias in history_text:
            weight = 4.0  # follow-ups: "and the errors?" after a service question
        if weight:
            for metric in metrics:
                scores[metric] = scores.get(metric, 0.0) + weight

    for metric in index.metric_queries:
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
    return _golden_set(index, available, k)


def _golden_set(index: MonitorsIndex, available: set[str], k: int) -> list[str]:
    """One throughput-flavored and one error-flavored metric per service, capped
    at k — the default lens when the question names nothing specific."""
    by_service: dict[str, list[str]] = {}
    for metric in sorted(index.metric_queries):
        parts = metric.split(".")
        if len(parts) >= 2 and metric in available:
            by_service.setdefault(parts[1], []).append(metric)

    selected: list[str] = []
    for service, metrics in sorted(by_service.items()):
        throughput = [m for m in metrics if "rate" in m or "processed" in m or "consumption" in m]
        errors = [m for m in metrics if "error" in m or "dlt" in m or "failed" in m]
        for bucket in (throughput, errors):
            if bucket and len(selected) < k:
                selected.append(bucket[0])
    return selected[:k]
