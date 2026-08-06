"""The answerable-question catalog — user phrasing mapped to an exact query.

`data/questions.json` pairs the questions a non-technical user actually asks
("how many communications were ingested today?") with the Datadog query that
answers each one, plus the intent, the service, and the shape of the answer.
Resolving a question through it turns "reason about the platform" into "read
these three series and report a number", which is the difference between a
plausible-sounding paragraph and an answer.

**Hint layer, never authority** — the same contract the rest of `app/knowledge`
lives under, and it bites harder here: of the ~60 metrics this file names, a
large minority are not emitted by this org at all (several `_error_counter` and
`_api_latency` series exist only in the file). A catalog entry may *propose*
metrics; only the live registry decides which are real. Metrics it names that
the registry does not carry are never queried and never cited — they are
reported as a coverage gap instead, because "the platform does not measure that"
is a true answer and a confidently-wrong number is not.

Deterministic and offline: no LLM call, stdlib only.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.knowledge.text import tokens
from app.telemetry.builtin import default_query

#: Where the committed catalog lives.
DATA_PATH = Path(__file__).parent / "data" / "questions.json"

#: A fully-qualified metric name: a namespace, a service, and at least one more
#: segment. Two segments alone ("ec.centralised_audit") is a group prefix, not a
#: metric, and treating it as one would put an unqueryable name in the registry.
_FULL_METRIC_RE = re.compile(r"\b([a-z][a-z0-9_]*\.[a-z0-9_]+(?:\.[a-z0-9_]+)+)", re.I)

#: A group prefix mentioned on its own ("… all under ec.centralised_audit"), so
#: prose entries can be resolved against it. Both lookarounds matter: they stop
#: a two-segment window *inside* a longer dotted run from being read as a group.
_GROUP_RE = re.compile(r"(?<![.\w])([a-z][a-z0-9_]*\.[a-z0-9_]+)(?![.\w])", re.I)

#: Any dotted run, used to find the bare series names in a prose entry.
_DOTTED_RE = re.compile(r"(?<![.\w])([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)", re.I)

#: Datadog's space aggregators, as they appear before a metric name.
_AGGREGATIONS = ("sum", "avg", "min", "max", "count",
                 "p50", "p75", "p90", "p95", "p99")

#: Counter modifiers that change what the number MEANS, so they must survive.
_MODIFIERS = (".as_count()", ".as_rate()")

#: Words too common across the catalog to identify anything on their own.
_STOPWORDS = frozenset({
    "a", "and", "any", "are", "at", "by", "did", "do", "does", "for", "from",
    "get", "got", "had", "has", "have", "how", "in", "into", "is", "it", "its",
    "long", "many", "much", "of", "on", "or", "our", "s", "so", "that", "the",
    "their", "there", "they", "this", "to", "up", "vs", "was", "we", "were",
    "what", "when", "where", "which", "who", "why", "with",
})

#: A slot match (the lifecycle stage or object the entry is *about*) outweighs
#: loose question-word overlap: "ingest" hitting STG-001's `stage: ingested` is
#: what separates it from every other "how many messages …" question.
SLOT_WEIGHT = 4.0

#: How much of what the USER said an entry has to explain. Measured on the
#: asked side, not the entry side: entry-side coverage rewards short entries and
#: happily hands "how slow is the alert-fetch API?" to the entry about the
#: surveillance filter, because the two share "slow" and "fetch".
#:
#: Measured over the supplied catalog (see BUILD-LOG): every correct match
#: scores >= 0.68 and every wrong substitution <= 0.32, so 0.5 sits in the gap.
#: Substitution is the failure that matters — a near-miss entry attaches a
#: confident "these series answer it" block to series that answer something else.
MIN_RECALL = 0.5

#: What a question asks FOR, which word overlap alone cannot see: "how many
#: messages did we ingest?" and "how fast is the indexer ingesting messages?"
#: share their content words almost exactly and want opposite metrics — a
#: counter and a latency histogram.
_INTENT_FAMILIES: dict[str, str] = {
    "COUNT_STAGE": "count", "COUNT_OUTCOME": "count", "FUNNEL_RATIO": "count",
    "THROUGHPUT": "count", "RECON": "count",
    "LATENCY": "latency",
    "ERROR_RATE": "error", "DEADLETTER": "error",
    "API_HEALTH": "health", "SAMPLING_STATE": "health",
}

#: Cue phrases, longest first so "how many" is tested before "many".
_INTENT_CUES: tuple[tuple[str, str], ...] = (
    ("how slow", "latency"), ("how long", "latency"), ("how fast", "latency"),
    ("response time", "latency"), ("taking", "latency"), ("latency", "latency"),
    ("duration", "latency"), ("p50", "latency"), ("p95", "latency"), ("p99", "latency"),
    ("dead letter", "error"), ("dead lettered", "error"), ("dlt", "error"),
    ("erroring", "error"), ("error", "error"), ("failing", "error"),
    ("failure", "error"), ("failed", "error"),
    ("how many", "count"), ("how much", "count"), ("number of", "count"),
    ("throughput", "count"), ("per second", "count"), ("volume", "count"),
    ("count", "count"), ("total", "count"),
)

#: A stated family is a hard gate, not a preference. "Is the KPI consumer
#: erroring?" answered from a consumption-rate counter is not a worse answer to
#: the question asked — it is a confident answer to a different one, and this
#: org emits no error counter for it, so the honest result is no match at all.


def _root(word: str) -> str:
    """A crude, closed stem so "ingested"/"ingesting"/"ingest" are one term.

    Deliberately conservative: only these three endings, and never below four
    characters, so "count"/"country" stay distinct. Plurals go through "s" alone
    — adding an "es" rule made the stemmer inconsistent with itself
    ("messages" -> "messag" but "communications" -> "communication"), which is
    worse than a slightly crude stem, because matching compares two stemmed
    strings and only agreement matters.
    """
    for suffix in ("ing", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


#: The one synonym set this platform cannot be understood without. Its metrics,
#: monitors and catalog questions say "communication"; every person asking about
#: it says "message". Without this, "how many messages did we ingest?" and "how
#: many communications were ingested?" score as different questions.
_SYNONYMS: dict[str, str] = {
    "comm": "message", "communication": "message", "msg": "message",
    "message": "message",
}


def _terms(text: str | None) -> set[str]:
    return {
        _SYNONYMS.get(root, root)
        for root in (_root(t) for t in tokens(text) if t not in _STOPWORDS and len(t) > 2)
    }


def _asked_family(question: str | None) -> str:
    """Which family of answer the question wants, or "" when it doesn't say."""
    from app.knowledge.text import normalize

    haystack = normalize(question)
    for cue, family in _INTENT_CUES:
        if f" {cue} " in haystack:
            return family
    return ""


def metrics_in(query: str | None) -> tuple[str, ...]:
    """Every metric name a `resolvedQuery` refers to, in order of appearance.

    Handles the three ways the file writes them: as a real query
    (`sum:ec.a.b{*}.as_count()`), several of them combined with `/`, `;` or
    `vs`, and — for the funnel entries — as prose that lists bare series names
    and states the group once at the end ("… (all under ec.centralised_audit)").
    """
    text = query or ""
    groups = [m.group(1) for m in _GROUP_RE.finditer(text)]

    # A standalone group prefix means this entry writes its series as prose:
    # bare names, with the namespace stated once. Without one, every dotted run
    # of three or more segments is already a fully-qualified metric.
    found: list[str] = []
    if groups:
        prefix = groups[-1]
        for match in _DOTTED_RE.finditer(text):
            run = match.group(1).rstrip(".")
            if run in groups:
                continue
            name = run if run.startswith(f"{prefix}.") else f"{prefix}.{run}"
            if name not in found:
                found.append(name)
        return tuple(found)

    for match in _FULL_METRIC_RE.finditer(text):
        name = match.group(1).rstrip(".")
        if name.count(".") >= 2 and name not in found:
            found.append(name)
    return tuple(found)


def query_for(metric: str, resolved_query: str | None) -> str:
    """The single-series Datadog query for `metric`, as this entry intends it.

    Preserves what the catalog knows and the adapter cannot guess — the space
    aggregation (`sum:` vs `p95:`) and the counter modifier (`.as_count()`) —
    while normalizing what would break at query time:

      - the scope is reset to `{*}`, because the adapter rewrites the first brace
        block from the investigation Scope and a hardcoded `{tenant:msprod}`
        would fight the user's own selection;
      - `by {tenant, pipeline_name}` grouping is dropped, because `get_metric`
        reads only the first series returned, so a grouped query would answer for
        one arbitrary tenant while looking platform-wide;
      - `top(…)` and multi-query strings are unwrapped to the one metric asked for.

    A metric named only in prose carries no aggregation, so it falls back to the
    shape-derived default (a counter is summed, a latency averaged).
    """
    text = resolved_query or ""
    index = text.find(metric)
    if index == -1:
        return default_query(metric)

    head = text[:index].rstrip()
    aggregation = ""
    if head.endswith(":"):
        candidate = re.split(r"[^a-z0-9]", head[:-1], flags=re.I)[-1].lower()
        if candidate in _AGGREGATIONS:
            aggregation = candidate
    if not aggregation:
        return default_query(metric)

    tail = text[index + len(metric):]
    tail = re.sub(r"^\{[^}]*\}", "", tail)          # the scope block
    tail = re.sub(r"^\s*by\s*\{[^}]*\}", "", tail)  # the grouping block
    modifier = next((m for m in _MODIFIERS if tail.startswith(m)), "")
    return f"{aggregation}:{metric}{{*}}{modifier}"


@dataclass(frozen=True)
class QuestionEntry:
    """One catalog question: how it is asked, and what answers it."""

    id: str
    question: str
    intent: str = ""
    service: str = ""
    resolved_query: str = ""
    answer_shape: str = ""
    confidence: str = ""
    note: str = ""
    metrics: tuple[str, ...] = ()
    #: The lifecycle stage / outcome / object this entry is about.
    slots: tuple[str, ...] = ()
    terms: frozenset[str] = field(default_factory=frozenset)

    def live_metrics(self, available) -> tuple[str, ...]:
        """The metrics this entry names that the registry can actually query."""
        return tuple(m for m in self.metrics if m in available)

    def missing_metrics(self, available) -> tuple[str, ...]:
        """The metrics it names that this platform does not emit."""
        return tuple(m for m in self.metrics if m not in available)

    def queries(self, available) -> dict[str, str]:
        return {m: query_for(m, self.resolved_query) for m in self.live_metrics(available)}


@dataclass(frozen=True)
class QuestionMatch:
    """A user question resolved onto a catalog entry."""

    entry: QuestionEntry
    metrics: tuple[str, ...]
    queries: dict[str, str]
    missing: tuple[str, ...] = ()

    def describe(self) -> str:
        """The prompt block. States what was asked for, which series answer it,
        and — critically — which named series this platform does not emit, so a
        partial answer is reported as partial instead of as a whole."""
        if not self.metrics:
            return (
                "UNANSWERABLE QUESTION (this is a known question, and this platform "
                "emits NO metric that answers it). Say so plainly as an Unknown, name "
                "the series that would be needed, and do NOT substitute a nearby "
                "metric as if it were the answer:\n"
                f"- catalog entry: {self.entry.id} — {self.entry.question}\n"
                "- required but not emitted here:\n"
                + "\n".join(f"    {metric}" for metric in self.missing)
            )
        lines = [
            "RESOLVED QUESTION (this matches a known, metric-answerable question — "
            "answer it directly from the series below, and state the number):",
            f"- catalog entry: {self.entry.id} — {self.entry.question}",
            f"- intent: {self.entry.intent or 'unspecified'}",
            f"- expected answer shape: {self.entry.answer_shape or 'a measurement'}",
        ]
        if self.metrics:
            lines.append("- series that answer it:")
            lines.extend(
                f"    {metric}  ->  {self.queries.get(metric, '')}" for metric in self.metrics)
        if self.missing:
            lines.append(
                "- named by the playbook but NOT emitted by this platform "
                "(report as an Unknown / coverage gap, never as a zero):")
            lines.extend(f"    {metric}" for metric in self.missing)
        if self.entry.note:
            lines.append(f"- note: {self.entry.note}")
        return "\n".join(lines)


def _slots_of(parsed: object) -> tuple[str, ...]:
    """The stage / outcome / object slots, flattened. These say what the entry is
    ABOUT, as opposed to how its question happens to be worded."""
    if not isinstance(parsed, dict):
        return ()
    out: list[str] = []
    for key in ("stage", "stages", "outcome", "object", "groupBy"):
        value = parsed.get(key)
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            out.extend(v for v in value if isinstance(v, str))
    return tuple(s for s in out if s and s not in ("ALL", "*"))


def load_question_catalog(path: Path | str | None = None) -> tuple[QuestionEntry, ...]:
    """Parse the committed catalog. Never raises: a missing, malformed or
    unexpectedly-shaped file yields an empty catalog and every seam that consumes
    it falls back to the behaviour it had before this layer existed."""
    target = Path(path) if path is not None else DATA_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ()
    if not isinstance(data, dict):
        return ()
    raw = data.get("questions")
    if not isinstance(raw, list):
        return ()

    entries: list[QuestionEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            continue
        parsed = item.get("parsed") if isinstance(item.get("parsed"), dict) else {}
        resolved = item.get("resolvedQuery") if isinstance(item.get("resolvedQuery"), str) else ""
        slots = _slots_of(parsed)
        entries.append(QuestionEntry(
            id=str(item.get("id") or ""),
            question=question.strip(),
            intent=str(parsed.get("intent") or ""),
            service=str(parsed.get("service") or ""),
            resolved_query=resolved,
            answer_shape=str(item.get("answerShape") or ""),
            confidence=str(item.get("confidence") or ""),
            note=str(item.get("note") or ""),
            metrics=metrics_in(resolved),
            slots=slots,
            terms=frozenset(_terms(question)),
        ))
    return tuple(entries)


def guard_phrases(catalog: tuple[QuestionEntry, ...]) -> tuple[str, ...]:
    """On-topic phrases for the relevance guard, drawn from the catalog.

    A question this catalog can answer must never be refused before reasoning
    starts — that is the one guard failure with no recovery. The phrases come
    from what each entry is *about*: its service and its stage/outcome slots.

    **Multi-word only.** `guard.evaluate` matches extra vocabulary as a plain
    substring, so contributing single words like "message", "status" or "item"
    would fast-allow nearly anything and undo the deliberate Stage-1 tightening.
    "supervised item update" cannot appear by accident.
    """
    phrases: set[str] = set()
    for entry in catalog or ():
        candidates = list(entry.slots)
        if entry.service:
            candidates.append(re.sub(r"^ec[-_]", "", entry.service))
        for candidate in candidates:
            words = re.sub(r"[^a-z0-9]+", " ", candidate.lower()).split()
            if len(words) >= 2:
                phrases.add(" ".join(words))
    return tuple(sorted(phrases))


def _idf(catalog: tuple[QuestionEntry, ...]) -> dict[str, float]:
    """Inverse document frequency over the catalog's own questions.

    "how many" appears in half the entries and identifies nothing; "enrichment",
    "funnel" and "dead-lettered" appear once and identify everything. Without
    this, every "how many messages …" question collapses onto whichever entry
    happens to sort first.
    """
    total = max(len(catalog), 1)
    counts: dict[str, int] = {}
    for entry in catalog:
        for term in entry.terms:
            counts[term] = counts.get(term, 0) + 1
    return {term: math.log(1 + total / count) for term, count in counts.items()}


def _best_entry(
    question: str | None,
    catalog: tuple[QuestionEntry, ...],
    available,
    answerable: bool,
) -> QuestionEntry | None:
    """The entry that best fits `question`, among those that can (or cannot)
    be answered from `available`.

    Ranking is IDF-weighted term overlap plus a heavier weight on the entry's
    stage/outcome slots. Two gates keep it from answering a question nobody
    asked: the intent family must agree when the question states one, and the
    entry must explain at least MIN_RECALL of what the user actually said.
    Fully deterministic — ties break on the catalog id.
    """
    asked = _terms(question)
    if not asked or not catalog or not available:
        return None

    weights = _idf(catalog)
    family = _asked_family(question)
    asked_weight = sum(weights.get(term, 0.0) for term in asked)
    if asked_weight <= 0:
        return None  # nothing the catalog has a word for

    best: tuple[float, str] | None = None
    winner: QuestionEntry | None = None

    for entry in catalog:
        if bool(entry.live_metrics(available)) is not answerable:
            continue
        if family and _INTENT_FAMILIES.get(entry.intent, "") != family:
            continue
        matched = sum(weights.get(term, 0.0) for term in entry.terms & asked)
        if matched / asked_weight < MIN_RECALL:
            continue
        score = matched
        for slot in entry.slots:
            if _terms(slot) & asked:
                score += SLOT_WEIGHT
        if score <= 0:
            continue
        key = (score, entry.id)
        if best is None or (-key[0], key[1]) < (-best[0], best[1]):
            best, winner = key, entry
    return winner


def match_question(
    question: str | None,
    catalog: tuple[QuestionEntry, ...],
    available,
) -> QuestionMatch | None:
    """The catalog entry that best answers `question`, or None.

    Only entries with at least one metric in `available` can be returned: an
    entry whose series this org does not emit cannot answer anything, and
    offering it would attach a query to a conclusion that can never run.
    """
    winner = _best_entry(question, catalog, available, answerable=True)
    if winner is None:
        return None
    return QuestionMatch(
        entry=winner,
        metrics=winner.live_metrics(available),
        queries=winner.queries(available),
        missing=winner.missing_metrics(available),
    )


def match_unanswerable(
    question: str | None,
    catalog: tuple[QuestionEntry, ...],
    available,
) -> QuestionMatch | None:
    """The entry this question IS, when none of its series are emitted here.

    Roughly half the catalog names metrics this org does not emit (a `_dlt_`
    counter, an `_api_error_counter`, an indexing-error counter). Those
    questions cannot be answered — but they can be answered *about*: "this
    platform emits no indexing-error metric" is a true, useful, checkable
    reply, and far better than quietly showing an adjacent series and letting
    the number look like the answer.

    Returned separately from `match_question` so it can never be mistaken for
    evidence: it carries no metrics and no queries, only the gap.
    """
    winner = _best_entry(question, catalog, available, answerable=False)
    if winner is None:
        return None
    return QuestionMatch(
        entry=winner, metrics=(), queries={}, missing=winner.metrics)
