"""Deterministic question interpretation: user words -> platform meaning.

`interpret()` answers "what did they actually ask?" — which service, which
lifecycle stage, which family of metric, over what window — with no LLM call, so
the same question always resolves identically and every rule is testable.

`candidate_metrics()` then answers "which real series could answer it?" and is
where the HINT-LAYER contract is enforced: the knowledge files propose, the live
registry disposes. Nothing is ever returned that the data source cannot query.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.knowledge.text import phrase_in
from app.knowledge.vocabulary import Vocabulary

#: Which metric type wins when a question matches several. A question is nearly
#: always phrased as "how many <qualifier>", so the qualifier ("errors",
#: "dead-lettered", "backed up") is the real intent and the generic counting word
#: is the fallback. Hence `counter` sits last.
_METRIC_TYPE_PRECEDENCE = (
    "dlt_counter",
    "error_counter",
    "infra_kafka_lag",
    "infra_pod",
    "latency",
    "gauge",
    "counter",
)


@dataclass(frozen=True)
class Interpretation:
    """What the copilot understood, in the platform's own terms."""

    question: str = ""
    intent: str | None = None
    services: tuple[str, ...] = ()
    objects: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    metric_type: str | None = None
    percentile: str | None = None
    time_range: str | None = None
    #: configured monitor modules the question names
    monitors: tuple[str, ...] = ()
    #: dashboard modules the question names
    dashboards: tuple[str, ...] = ()
    #: (repo, order, stage name) for each resolved service in the lifecycle
    stages: tuple[tuple[str, int, str], ...] = ()
    #: (phrase, kind, canonical) for every phrase that matched
    matched: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not self.matched

    def describe(self) -> str:
        """A compact `RESOLVED TERMS` block for the reasoning prompt.

        Shows the model how each user word was mapped, so a claim can name the
        service and stage it came from instead of paraphrasing the question.
        """
        if self.is_empty:
            return ""

        lines: list[str] = []
        stage_by_repo = {repo: (order, name) for repo, order, name in self.stages}
        for repo in self.services:
            typed = [p for p, kind, c in self.matched if kind == "service" and c == repo]
            said = f'"{typed[0]}" → ' if typed else ""
            stage = stage_by_repo.get(repo)
            where = f" (stage {stage[0]}: {stage[1]})" if stage else ""
            lines.append(f"- {said}{repo}{where}")

        for module in self.monitors:
            lines.append(f"- monitor {module}")
        for module in self.dashboards:
            lines.append(f"- dashboard {module}")

        for phrase, kind, canonical in self.matched:
            if kind in ("concept", "object", "stage") and canonical != phrase:
                lines.append(f'- "{phrase}" → {canonical}')

        asked: list[str] = []
        if self.intent:
            asked.append(f"intent {self.intent}")
        if self.metric_type:
            asked.append(f"metric family {self.metric_type}")
        if self.percentile:
            asked.append(f"percentile {self.percentile}")
        if self.time_range:
            asked.append(f"window {self.time_range}")
        if asked:
            lines.append("- " + ", ".join(asked))

        return "RESOLVED TERMS (how the question maps to this platform):\n" + "\n".join(
            dict.fromkeys(lines)  # de-duplicate, preserve order
        )


def interpret(question: str | None, vocab: Vocabulary) -> Interpretation:
    """Resolve a question against the vocabulary. Never raises."""
    text = question or ""
    if not text.strip() or vocab.is_empty:
        return Interpretation(question=text)

    matched: list[tuple[str, str, str]] = []
    for phrase, meanings in vocab.phrases.items():
        if phrase_in(text, phrase):
            matched.extend((phrase, m.kind, m.canonical) for m in meanings)

    if not matched:
        return Interpretation(question=text)

    services = _canonicals(matched, "service")
    metric_type = _pick_metric_type(matched)

    stages: list[tuple[str, int, str]] = []
    for repo in services:
        stage = vocab.stage_of(repo)
        if stage:
            stages.append((repo, stage[0], stage[1]))

    percentile = _first(matched, "percentile")
    if percentile is None and metric_type == "latency":
        percentile = vocab.defaults.get("PERCENTILE")

    return Interpretation(
        question=text,
        intent=vocab.intent_by_metric_type.get(metric_type or ""),
        services=services,
        objects=_canonicals(matched, "object"),
        concepts=_canonicals(matched, "concept"),
        metric_type=metric_type,
        percentile=percentile,
        time_range=_first(matched, "time_range") or vocab.defaults.get("TIME_RANGE"),
        monitors=_canonicals(matched, "monitor", "monitor_utterance"),
        dashboards=_canonicals(matched, "dashboard", "dashboard_utterance"),
        stages=tuple(stages),
        matched=tuple(sorted(set(matched))),
    )


def candidate_metrics(
    interpretation: Interpretation,
    vocab: Vocabulary,
    available,
    limit: int | None = None,
) -> list[str]:
    """Real metric names that could answer this question, best-scoped first.

    Three narrowing passes — service, then metric family, then the operation the
    user named — each applied only when it leaves something behind, so an
    over-specific question degrades to the broader set instead of to nothing.

    `available` is the authority throughout. A metric the knowledge files name
    but the registry does not carry is never returned: those files are partly
    inferred, and citing a series that cannot return data would put invented
    support behind a conclusion.
    """
    if interpretation.is_empty or not available:
        return []

    # A named monitor is the sharpest signal there is: it watches one specific
    # series for exactly the condition being asked about, so its metrics lead.
    named = [
        metric
        for module in interpretation.monitors
        for metric in vocab.monitor_metrics.get(module, ())
        if metric in available
    ]

    segments: set[str] = set()
    for repo in interpretation.services:
        segments.update(vocab.metric_segments(repo, available))
    if not segments:
        return _dedupe(named)[:limit] if limit else _dedupe(named)

    pool = [
        name for name in sorted(available)
        if name.count(".") >= 2 and name.split(".")[1] in segments
    ]

    suffixes = vocab.suffixes_by_metric_type.get(interpretation.metric_type or "", ())
    pool = _narrow(pool, lambda m: any(m.endswith(s) for s in suffixes)) if suffixes else pool

    op_tokens: set[str] = set()
    for obj in interpretation.objects:
        op_tokens.update(vocab.op_tokens_by_object.get(obj, ()))
    if op_tokens:
        pool = _narrow(pool, lambda m: any(t in m.lower() for t in op_tokens))

    ranked = _dedupe(named + pool)
    return ranked[:limit] if limit else ranked


def _dedupe(names: list[str]) -> list[str]:
    """Order-preserving, so monitor-named series stay ahead of the broader pool."""
    return list(dict.fromkeys(names))


def _narrow(pool: list[str], predicate) -> list[str]:
    """Apply a filter only if it keeps something — an empty result means the
    filter was too specific for this registry, not that there is no answer."""
    kept = [m for m in pool if predicate(m)]
    return kept or pool


def _canonicals(matched, *kinds: str) -> tuple[str, ...]:
    return tuple(sorted({c for _, k, c in matched if k in kinds}))


def _first(matched, kind: str) -> str | None:
    values = _canonicals(matched, kind)
    return values[0] if values else None


def _pick_metric_type(matched) -> str | None:
    found = {c for _, kind, c in matched if kind == "metric_type"}
    for metric_type in _METRIC_TYPE_PRECEDENCE:
        if metric_type in found:
            return metric_type
    return next(iter(sorted(found)), None)
