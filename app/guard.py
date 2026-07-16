"""Relevance & abuse guard — the pre-reasoning gate.

Decides whether a user message is a genuine observability question BEFORE the
expensive reasoning path runs, so we neither spend tokens on off-topic requests
nor let prompt-injection reach the model.

Two stages, cheapest first:
  - Stage 1 is deterministic and free (zero tokens): block empty / over-long /
    injection attempts; fast-allow clearly on-topic questions and short in-context
    follow-ups.
  - Stage 2 handles only the ambiguous middle. In "hybrid" mode a cheap classifier
    is consulted; in "deterministic" mode (or when no classifier is available) the
    ambiguous message is refused. The classifier failing counts as "refuse" — the
    gate fails closed.

Everything here is pure: no network, no I/O. The classifier is injected so the
module stays testable and offline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

# Default ceiling on message length (characters). Overridable per call / via config.
DEFAULT_MAX_CHARS = 2000

# A short in-context follow-up ("why?", "and the db?") is allowed without a
# classifier only when an investigation is already underway.
_FOLLOWUP_MAX_WORDS = 4

_REFUSAL = (
    "I'm the Observability Copilot — I investigate system health, telemetry, and "
    "incidents. I can't help with that, but ask me about latency, errors, deploys, "
    "or an incident and I'll dig in with evidence."
)

# Prompt-injection / role-hijack patterns (checked before anything is allowed).
_INJECTION_PATTERNS = [
    re.compile(p) for p in (
        r"ignore\s+.*instruction",
        r"disregard\s+.*(instruction|above|prior|previous)",
        r"forget\s+.*(instruction|everything|above)",
        r"you\s+are\s+now",
        r"system\s+prompt",
        r"reveal\s+your\s+(system|initial|hidden)",
        r"pretend\s+to\s+be",
        r"general[-\s]purpose\s+assistant",
        r"act\s+as\s+a\s+(chatbot|general)",
    )
]

# Vocabulary that marks a message as clearly on-topic (single tokens are matched
# on word boundaries; phrases are matched as substrings). Deliberately precise —
# generic words like "change" or "worse" are excluded so genuinely ambiguous
# messages fall through to Stage 2 rather than being auto-allowed.
_ONTOPIC_PHRASES = (
    "root cause", "error rate", "hit ratio", "response time",
    "message processing", "quota manager", "config curator", "policy evaluator",
    "review service", "dead letter", "alert rule", "memory leak", "per second",
)
_ONTOPIC_WORDS = (
    # Performance & behavior
    "latency", "p50", "p95", "p99", "deploy", "deployment", "rollback", "slow",
    "slowness", "error", "errors", "5xx", "4xx", "timeout", "healthy", "health",
    "unhealthy", "cpu", "memory", "disk", "throughput", "rps", "qps", "traffic",
    "incident", "outage", "downtime", "slo", "sla", "trace", "traces", "span",
    "metric", "metrics", "dashboard", "spike", "spiking", "saturation", "cache",
    "database", "checkout", "api", "endpoint", "service", "alert", "anomaly",
    "regression", "degraded", "crash", "restart", "throttl",
    # Monitors & alerting configuration
    "monitor", "monitors", "alerting", "alerts", "notification", "notifications",
    "threshold", "alarm", "terraform", "monitoring",
    # EC service names (single-token; multi-word ones live in _ONTOPIC_PHRASES)
    "debezium", "indexer", "lookback", "surveillance", "audit", "gateway",
    # Queue & processing concepts
    "queue", "consumer", "lag", "backlog", "retry", "dlt", "backpressure",
    "processed", "pending",
    # Infrastructure
    "pod", "container", "kubernetes", "replica",
    # Performance issues
    "delay", "bottleneck", "contention", "deadlock", "saturated",
)
_ONTOPIC_WORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _ONTOPIC_WORDS) + r")\b"
)


@dataclass(frozen=True)
class GuardVerdict:
    allowed: bool
    category: str                 # ok | empty | too_long | injection | off_topic
    used_classifier: bool = False
    refusal: str = ""


def _is_injection(text: str) -> bool:
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def _is_on_topic(text: str) -> bool:
    if any(phrase in text for phrase in _ONTOPIC_PHRASES):
        return True
    return _ONTOPIC_WORD_RE.search(text) is not None


def evaluate(
    message: str,
    *,
    has_context: bool = False,
    mode: str = "hybrid",
    max_chars: int = DEFAULT_MAX_CHARS,
    classifier: Callable[[str], bool] | None = None,
) -> GuardVerdict:
    """Return a verdict for `message`.

    `has_context` = an investigation is already active (enables short follow-ups).
    `mode` = "hybrid" (consult the classifier for the ambiguous middle) or
    "deterministic" (refuse the ambiguous middle without a classifier).
    `classifier(message) -> bool` decides relevance for ambiguous messages; a
    missing classifier or one that raises fails closed (refuse).
    """
    text = (message or "").strip()

    # --- Stage 1: deterministic, zero-token ---
    if not text:
        return GuardVerdict(False, "empty", refusal=_REFUSAL)
    if len(text) > max_chars:
        return GuardVerdict(False, "too_long", refusal=_REFUSAL)

    low = text.lower()
    if _is_injection(low):
        return GuardVerdict(False, "injection", refusal=_REFUSAL)

    if _is_on_topic(low):
        return GuardVerdict(True, "ok")

    if has_context and len(text.split()) <= _FOLLOWUP_MAX_WORDS:
        return GuardVerdict(True, "ok")

    # --- Stage 2: the ambiguous middle ---
    if mode == "deterministic" or classifier is None:
        return GuardVerdict(False, "off_topic", refusal=_REFUSAL)

    try:
        relevant = bool(classifier(text))
    except Exception:
        # Fail closed: if the classifier is unavailable, refuse rather than spend
        # the reasoning path on a message we couldn't vet.
        return GuardVerdict(False, "off_topic", used_classifier=True, refusal=_REFUSAL)

    if relevant:
        return GuardVerdict(True, "ok", used_classifier=True)
    return GuardVerdict(False, "off_topic", used_classifier=True, refusal=_REFUSAL)
