"""Flattens the knowledge files into one phrase -> meaning lookup.

The source files are shaped for humans (nested entities, per-repo catalogs,
lifecycle stages). The interpreter needs the inverse: given a phrase a user
typed, what does it mean? `build_vocabulary` performs that inversion once, at
startup, and everything downstream is a dict lookup.

Every accessor is defensive about shape. These files are curated by hand and
partially self-declared "inferred", so a missing key must degrade to "no
meaning" rather than raise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.knowledge.loader import KnowledgeBase

#: Shortest phrase safe to expose as guard vocabulary. The guard matches these
#: as plain SUBSTRINGS, so a 1-3 character phrase would appear in nearly every
#: message and fast-allow everything — disabling the gate it was meant to inform.
MIN_PHRASE_LEN = 4

#: A groupName we can trust, e.g. "ec.indexer". The files use human placeholders
#: like "(not read)" and "(underscore-style; not read)" where the real value was
#: never confirmed; those must never be treated as a metric prefix.
_GROUP_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_.]+$")

#: Phrases carrying an unfilled slot ("for {name}") are templates, not vocabulary.
_TEMPLATE_RE = re.compile(r"[{}<>]")

#: A fully-qualified metric series: at least three dot-separated segments, so
#: "ec.reporting.pending_pipelines_count" matches but the bare service prefix
#: "ec.quota_manager" and the placeholder "<service.prefix>" do not.
_METRIC_NAME_RE = re.compile(r"\b[a-z][a-z0-9_]*(?:\.[a-z0-9_]+){2,}\b")

#: Kinds safe to hand the relevance guard. Monitor/dashboard SYNONYMS qualify
#: ("gateway board", "ingest spike"); the example UTTERANCES they sit beside do
#: not — a whole sentence is useless as substring vocabulary.
_GUARD_KINDS = ("service", "concept", "object", "stage", "monitor", "dashboard")

#: Kinds whose SINGLE-word phrases are still specific enough to fast-allow on.
#: "sampler" and "debezium" name this platform; "message" and "status" do not.
_SPECIFIC_KINDS = ("service", "monitor", "dashboard")


@dataclass(frozen=True)
class Phrase:
    """One meaning of one user phrase."""

    text: str        # the lowercase phrase as a user would type it
    kind: str        # "service" | "object" | "metric_type" | "concept" |
                     # "time_range" | "percentile" | "stage" | "monitor" |
                     # "dashboard" | "monitor_utterance" | "dashboard_utterance"
    canonical: str   # the canonical token, e.g. "ec-surveillance-quota-manager"


@dataclass
class Vocabulary:
    """Inverted knowledge: phrase -> meanings, plus the lookup tables the
    interpreter needs to turn a meaning into candidate metrics."""

    phrases: dict[str, tuple[Phrase, ...]] = field(default_factory=dict)
    #: canonical metric_type -> the intent it resolves to ("latency" -> GET_LATENCY)
    intent_by_metric_type: dict[str, str] = field(default_factory=dict)
    #: canonical metric_type -> metric-name suffixes ("latency" -> ("_latency", ...))
    suffixes_by_metric_type: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: canonical object -> operation tokens found inside metric names
    op_tokens_by_object: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: repo -> explicitly declared, trustworthy groupName
    group_names: dict[str, str] = field(default_factory=dict)
    #: repo -> alternative repo names ("aka")
    repo_akas: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: repo -> (order, stage name) in the communication lifecycle
    stages: dict[str, tuple[int, str]] = field(default_factory=dict)
    #: the default canonical value per entity ("TIME_RANGE" -> "1d")
    defaults: dict[str, str] = field(default_factory=dict)
    #: monitor module -> the metric series it actually watches
    monitor_metrics: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: metric service segment -> repo, for segments that name exactly one repo
    _repo_by_segment: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.phrases

    def lookup(self, text: str) -> tuple[Phrase, ...]:
        return self.phrases.get((text or "").strip().lower(), ())

    def guard_phrases(self) -> tuple[str, ...]:
        """Phrases safe to hand the relevance guard as on-topic vocabulary.

        The guard matches these as plain SUBSTRINGS and fast-allows on a hit, so
        admitting ordinary English would disable the very gate this informs. Two
        rules keep that from happening:

          - a MULTI-WORD phrase is inherently specific ("quota manager",
            "gateway board", "ingest spike") and is always safe;
          - a SINGLE word is admitted only when it names a service, monitor or
            dashboard — this platform's own nouns. The domain concepts and
            lifecycle objects contribute words like "message", "record" and
            "status", which are English, not evidence of an observability
            question. Stage 2 owns that ambiguous middle by design.

        Metric-type words ("errors", "how many") are excluded outright.
        """
        return tuple(sorted({
            p.text
            for meanings in self.phrases.values()
            for p in meanings
            if p.kind in _GUARD_KINDS
            and len(p.text) >= MIN_PHRASE_LEN
            and (" " in p.text or p.kind in _SPECIFIC_KINDS)
        }))

    def stage_of(self, repo: str) -> tuple[int, str] | None:
        return self.stages.get(repo)

    def attribute(self, metric_name: str) -> tuple[str | None, str | None]:
        """(repo, "order stage") for a metric name, from its service segment.

        "ec.indexer.ingested_communication_consumption_rate" -> ("ec-indexer",
        "8 indexed"). Only segments that identify exactly ONE repo are mapped:
        segment derivation is intentionally over-generous, so generic tails like
        "service" reach several repos and must not silently pick one.
        """
        if metric_name.count(".") < 2:
            return None, None
        repo = self._repo_by_segment.get(metric_name.split(".")[1])
        if repo is None:
            return None, None
        stage = self.stages.get(repo)
        return repo, f"{stage[0]} {stage[1]}" if stage else None

    def metric_segments(self, repo: str, available) -> tuple[str, ...]:
        """The metric-name service segments for `repo` that actually exist.

        "ec.quota_manager.pipeline_processed_counter" has segment "quota_manager".
        A declared groupName is used when trustworthy; otherwise segments are
        derived from the repo name (and its `aka`) and — always — confirmed
        against `available`. Derivation guesses freely precisely because the
        registry filters the guesses: a wrong candidate simply matches nothing.
        """
        present = {
            name.split(".")[1]
            for name in available
            if name.count(".") >= 2
        }
        return tuple(sorted(self._segment_candidates(repo) & present))

    def _segment_candidates(self, repo: str) -> set[str]:
        candidates: set[str] = set()

        group = self.group_names.get(repo, "")
        if group and "." in group:
            candidates.add(group.split(".", 1)[1].split(".")[0])

        for name in (repo, *self.repo_akas.get(repo, ())):
            parts = [p for p in name.removeprefix("ec-").split("-") if p]
            # Progressively drop leading qualifiers: a repo called
            # "ec-surveillance-quota-manager" emits under "quota_manager".
            for i in range(len(parts)):
                tail = parts[i:]
                candidates.add("_".join(tail))
                candidates.add("_".join(_singular(p) for p in tail))
        return {c for c in candidates if c}


def _singular(word: str) -> str:
    """Bridge repo-vs-metric plurality ("manual-runs-service" emits under
    "manual_run_service"). Deliberately naive — a wrong guess is filtered out by
    the registry intersection."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def build_vocabulary(kb: KnowledgeBase) -> Vocabulary:
    """Invert the knowledge base into a Vocabulary. Never raises."""
    vocab = Vocabulary()
    collected: dict[str, set[Phrase]] = {}

    def add(text: object, kind: str, canonical: str) -> None:
        phrase = (text or "") if isinstance(text, str) else ""
        phrase = phrase.strip().lower()
        if not phrase or _TEMPLATE_RE.search(phrase):
            return
        collected.setdefault(phrase, set()).add(Phrase(phrase, kind, canonical))

    _load_entities(kb, vocab, add)
    _load_intents(kb, vocab)
    _load_concepts(kb, add)
    _load_global_terms(kb, add)
    _load_lifecycle(kb, vocab, add)
    _load_repositories(kb, vocab)
    _load_monitors(kb, vocab, add)
    _load_dashboards(kb, add)
    _load_example_utterances(kb, add)

    vocab.phrases = {
        text: tuple(sorted(meanings, key=lambda p: (p.kind, p.canonical)))
        for text, meanings in sorted(collected.items())
    }
    vocab._repo_by_segment = _invert_segments(vocab)
    return vocab


def _invert_segments(vocab: Vocabulary) -> dict[str, str]:
    """segment -> repo, keeping only segments that identify a single repo."""
    owners: dict[str, set[str]] = {}
    for repo in vocab.stages:
        for segment in vocab._segment_candidates(repo):
            owners.setdefault(segment, set()).add(repo)
    return {s: next(iter(r)) for s, r in owners.items() if len(r) == 1}


# --- per-source extraction -------------------------------------------------

def _entities(kb: KnowledgeBase) -> list[dict]:
    interface = kb.metrics_nlp.get("nlpInterface")
    if not isinstance(interface, dict):
        return []
    entities = interface.get("entities")
    return [e for e in entities if isinstance(e, dict)] if isinstance(entities, list) else []


#: entity name -> the Phrase.kind it contributes
_ENTITY_KINDS = {
    "SERVICE": "service",
    "OBJECT": "object",
    "METRIC_TYPE": "metric_type",
    "PERCENTILE": "percentile",
    "TIME_RANGE": "time_range",
    "STAGE": "stage",
}


def _load_entities(kb: KnowledgeBase, vocab: Vocabulary, add) -> None:
    for entity in _entities(kb):
        name = entity.get("name")
        kind = _ENTITY_KINDS.get(name)
        values = entity.get("canonicalValues")
        if not kind or not isinstance(values, dict):
            continue

        for canonical, spec in values.items():
            if not isinstance(spec, dict):
                continue
            # The canonical token itself is a phrase people type ("p95", "7d").
            add(canonical, kind, canonical)
            for synonym in _as_list(spec.get("synonyms")):
                add(synonym, kind, canonical)

            if spec.get("default") is True:
                vocab.defaults[name] = canonical
            if name == "METRIC_TYPE":
                suffixes = tuple(s for s in _as_list(spec.get("nameSuffixes")) if s)
                if suffixes:
                    vocab.suffixes_by_metric_type[canonical] = suffixes
            elif name == "OBJECT":
                tokens = tuple(t.lower() for t in _as_list(spec.get("opTokens")) if t)
                if tokens:
                    vocab.op_tokens_by_object[canonical] = tokens
            elif name == "SERVICE":
                group = spec.get("groupName") or spec.get("groupNameGuess") or ""
                if isinstance(group, str) and _GROUP_NAME_RE.match(group):
                    vocab.group_names.setdefault(canonical, group)


def _load_intents(kb: KnowledgeBase, vocab: Vocabulary) -> None:
    """metric_type -> intent, taken from each intent's own `resolvesTo`, so the
    mapping stays data-driven rather than hardcoded here."""
    interface = kb.metrics_nlp.get("nlpInterface")
    intents = interface.get("intents") if isinstance(interface, dict) else None
    for intent in intents if isinstance(intents, list) else []:
        if not isinstance(intent, dict):
            continue
        intent_id = intent.get("id")
        resolves = intent.get("resolvesTo")
        if not intent_id or not isinstance(resolves, dict):
            continue
        metric_type = resolves.get("metricType")
        # "counter|gauge" is deliberately ambiguous — skip it rather than let a
        # plain "how many" question claim the completion intent.
        if isinstance(metric_type, str) and "|" not in metric_type:
            vocab.intent_by_metric_type.setdefault(metric_type, intent_id)


def _load_concepts(kb: KnowledgeBase, add) -> None:
    """globalConcepts is where the crucial UI-vs-backend renames live —
    'queue' means pipeline, 'sample' means quota."""
    concepts = kb.nlp_grammar.get("globalConcepts")
    for concept in concepts if isinstance(concepts, list) else []:
        if not isinstance(concept, dict):
            continue
        canonical = concept.get("canonical")
        if not canonical:
            continue
        add(canonical.replace("_", " "), "concept", canonical)
        for synonym in _as_list(concept.get("userSynonyms")):
            add(synonym, "concept", canonical)


def _load_global_terms(kb: KnowledgeBase, add) -> None:
    """The monitors dictionary's cross-cutting terms (monitor, dashboard,
    consumer_lag, pod_health) and their everyday phrasings."""
    terms = kb.monitors_dictionary.get("globalTerms")
    for term in terms if isinstance(terms, list) else []:
        if not isinstance(term, dict):
            continue
        canonical = term.get("canonical")
        if not canonical:
            continue
        add(canonical.replace("_", " "), "concept", canonical)
        for synonym in _as_list(term.get("userSynonyms")):
            add(synonym, "concept", canonical)


def _load_lifecycle(kb: KnowledgeBase, vocab: Vocabulary, add) -> None:
    lifecycle = kb.nlp_grammar.get("stageLifecycle")
    stages = lifecycle.get("stages") if isinstance(lifecycle, dict) else None
    for stage in stages if isinstance(stages, list) else []:
        if not isinstance(stage, dict):
            continue
        name, repo, order = stage.get("stage"), stage.get("repo"), stage.get("order")
        if name and repo and isinstance(order, int):
            vocab.stages[repo] = (order, name)
        if name:
            add(name.replace("_", " "), "stage", name)
            for synonym in _as_list(stage.get("userSynonyms")):
                add(synonym, "stage", name)


def _load_repositories(kb: KnowledgeBase, vocab: Vocabulary) -> None:
    """Per-repo detail from both files: `aka` names (which supply the real metric
    segment for ec-queue-qualifier) and any trustworthy declared groupName."""
    repos = kb.nlp_grammar.get("repositories")
    for repo, spec in (repos if isinstance(repos, dict) else {}).items():
        if isinstance(spec, dict) and spec.get("aka"):
            vocab.repo_akas[repo] = tuple(_as_list(spec.get("aka")))

    metrics = kb.metrics_nlp.get("metrics")
    catalog = metrics.get("repositories") if isinstance(metrics, dict) else None
    for repo, spec in (catalog if isinstance(catalog, dict) else {}).items():
        if not isinstance(spec, dict):
            continue
        group = spec.get("groupName")
        if isinstance(group, str) and _GROUP_NAME_RE.match(group):
            vocab.group_names[repo] = group


def _load_monitors(kb: KnowledgeBase, vocab: Vocabulary, add) -> None:
    """Monitor modules, their everyday phrasings, and the series they watch.

    A monitor is the sharpest possible mapping from a question to telemetry:
    "are the pipelines finishing on time?" names exactly one monitor, which names
    exactly one metric. The `metric` field is prose in places ("composite: 8
    error counters ÷ ..."), so series are pattern-extracted rather than assumed.
    """
    monitors = kb.monitors_dictionary.get("monitors")
    for monitor in monitors if isinstance(monitors, list) else []:
        if not isinstance(monitor, dict):
            continue
        module = monitor.get("module")
        if not module:
            continue

        add(module.replace("_", " "), "monitor", module)
        for synonym in _as_list(monitor.get("userSynonyms")):
            add(synonym, "monitor", module)

        series = _metric_names(monitor.get("metric")) or _metric_names(monitor.get("query"))
        if series:
            vocab.monitor_metrics[module] = series


def _load_dashboards(kb: KnowledgeBase, add) -> None:
    """Dashboards carry no thresholds, but people ask for them by name ("the
    gateway board") and they are where an uncovered question gets answered."""
    dashboards = kb.monitors_dictionary.get("dashboards")
    for dashboard in dashboards if isinstance(dashboards, list) else []:
        if not isinstance(dashboard, dict):
            continue
        module = dashboard.get("module")
        if not module:
            continue
        add(dashboard.get("title"), "dashboard", module)
        for synonym in _as_list(dashboard.get("userSynonyms")):
            add(synonym, "dashboard", module)


def _load_example_utterances(kb: KnowledgeBase, add) -> None:
    """Worked examples map a whole sentence to a monitor or dashboard, covering
    phrasings no synonym list does. Matched verbatim, so they are exact wins
    only — and kept out of guard vocabulary, where a sentence is useless."""
    examples = kb.monitors_dictionary.get("examples")
    for example in examples if isinstance(examples, list) else []:
        if not isinstance(example, dict):
            continue
        utterance = example.get("utterance")
        parsed = example.get("parsed")
        if not isinstance(utterance, str) or not isinstance(parsed, dict):
            continue
        if isinstance(parsed.get("monitor"), str):
            add(utterance, "monitor_utterance", parsed["monitor"])
        if isinstance(parsed.get("dashboard"), str):
            add(utterance, "dashboard_utterance", parsed["dashboard"])


def _metric_names(value: object) -> tuple[str, ...]:
    """Fully-qualified series names mentioned anywhere in `value`."""
    found: set[str] = set()
    for text in _as_list(value):
        found.update(_METRIC_NAME_RE.findall(text))
    return tuple(sorted(found))


def _as_list(value: object) -> list[str]:
    """Tolerate a bare string where a list was expected, and drop non-strings."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []
