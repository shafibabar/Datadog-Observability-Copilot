"""Coverage gaps — the questions this platform genuinely cannot answer.

The monitors dictionary records two dangerous shapes, both of which look like
health when read naively:

  - **no monitor at all.** `kafka.consumer_lag` has 57 dashboard widgets and
    zero alert monitors, so "are we backed up?" can only ever be answered by
    reading a dashboard. No alert firing is not evidence of health.
  - **the no-data trap.** A monitor wired ahead of the metric it watches, or
    pointed at a prefix that never emits, reports green forever.

Surfacing these is the charter's Unknowns discipline made concrete: silence here
would let the copilot answer confidently from nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.knowledge.loader import KnowledgeBase
from app.knowledge.text import phrase_in
from app.knowledge.vocabulary import Vocabulary

#: Note fragments that mark a monitor as structurally incapable of alerting.
_TRAP_MARKERS = (
    "no-data",
    "no data",
    "never fire",
    "inert monitor",
    "green !=",
    "reads green",
    "may be suppressed",
)


@dataclass(frozen=True)
class Gap:
    """Something the question asked about that the platform cannot alert on."""

    topic: str    # the concept or monitor module concerned
    kind: str     # "no_monitor" | "no_data_trap"
    reason: str   # why the answer is unavailable or untrustworthy
    check: str    # where a human should look instead

    def render(self) -> str:
        label = self.topic.replace("_", " ")
        tail = f" — check {self.check}" if self.check else ""
        return f"{label}: {self.reason}{tail}"


def detection_gaps(
    question: str | None,
    kb: KnowledgeBase,
    vocab: Vocabulary | None = None,
) -> list[Gap]:
    """Gaps relevant to `question`, uncovered-first. Never raises; an empty
    knowledge base simply yields no gaps."""
    dictionary = kb.monitors_dictionary if isinstance(kb.monitors_dictionary, dict) else {}
    if not question or not dictionary:
        return []

    cases = _cases(dictionary)
    gaps = _uncovered_concepts(question, dictionary, cases)
    gaps.extend(_no_data_traps(question, dictionary))
    return gaps


def _uncovered_concepts(question: str, dictionary: dict, cases: list[dict]) -> list[Gap]:
    """globalTerms flagged `gap: true` — concepts with dashboards but no alert."""
    gaps: list[Gap] = []
    terms = dictionary.get("globalTerms")
    for term in terms if isinstance(terms, list) else []:
        if not isinstance(term, dict) or not term.get("gap"):
            continue
        canonical = term.get("canonical")
        if not canonical:
            continue

        synonyms = [canonical.replace("_", " "), *_strings(term.get("userSynonyms"))]
        if not any(phrase_in(question, s) for s in synonyms):
            continue

        case = _matching_case(synonyms, cases)
        gaps.append(Gap(
            topic=canonical,
            kind="no_monitor",
            reason=_text(term.get("note")) or _text(case.get("gap")),
            # A worked example names the actual widget group to open; the case's
            # answerVia is often just "dashboard only", which helps nobody.
            check=_example_answer(synonyms, dictionary) or _text(case.get("answerVia")),
        ))
    return gaps


def _example_answer(synonyms: list[str], dictionary: dict) -> str:
    """The resolution text from a gap-flagged worked example, if one covers this."""
    examples = dictionary.get("examples")
    for example in examples if isinstance(examples, list) else []:
        if not isinstance(example, dict) or not example.get("gap"):
            continue
        utterance = _text(example.get("utterance"))
        if any(phrase_in(utterance, s) for s in synonyms):
            return _text(example.get("resolved"))
    return ""


def _no_data_traps(question: str, dictionary: dict) -> list[Gap]:
    """Monitors whose own notes admit they can read green while blind."""
    gaps: list[Gap] = []
    monitors = dictionary.get("monitors")
    for monitor in monitors if isinstance(monitors, list) else []:
        if not isinstance(monitor, dict):
            continue
        note = _text(monitor.get("note"))
        if not (monitor.get("gap") or _is_trap(note)):
            continue
        module = monitor.get("module")
        if not module:
            continue
        if not any(phrase_in(question, s) for s in _strings(monitor.get("userSynonyms"))):
            continue

        gaps.append(Gap(
            topic=module,
            kind="no_data_trap",
            reason=note or "monitor may report green without data",
            check=_text(monitor.get("metric")) if isinstance(monitor.get("metric"), str) else "",
        ))
    return gaps


def _cases(dictionary: dict) -> list[dict]:
    section = dictionary.get("detectionGaps")
    cases = section.get("cases") if isinstance(section, dict) else None
    return [c for c in cases if isinstance(c, dict)] if isinstance(cases, list) else []


def _matching_case(synonyms: list[str], cases: list[dict]) -> dict:
    """The documented gap case whose user-ask uses one of these words."""
    for case in cases:
        ask = _text(case.get("userAsk"))
        if any(phrase_in(ask, s) for s in synonyms):
            return case
    return {}


def _is_trap(note: str) -> bool:
    lowered = note.lower()
    return any(marker in lowered for marker in _TRAP_MARKERS)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""
