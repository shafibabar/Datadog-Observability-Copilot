"""Spec for the reasoning layer: structured reasoning objects, timeline
reconstruction, evidence catalog, the LLM-client seam, and the engine.

Claude is fully mocked (FakeLLM / fake Anthropic client) — no key, no network,
no spend. Written test-first (TDD red) before the implementation exists.
"""
import sys
from types import SimpleNamespace

import pytest

from app.reasoning.engine import ReasoningEngine
from app.reasoning.evidence import build_evidence_catalog
from app.reasoning.llm import (
    AnthropicClient,
    ClaudeCliClient,
    _default_runner,
    cli_available,
    extract_json,
)
from app.reasoning.models import (
    Confidence,
    Hypothesis,
    ReasoningCategory,
    ReasoningObject,
)
from app.reasoning.timeline import build_timeline
from app.telemetry.replay import ReplayAdapter


# --- models ---------------------------------------------------------------

def test_confidence_parse_is_lenient():
    assert Confidence.parse("HIGH") == Confidence.HIGH
    assert Confidence.parse("medium") == Confidence.MEDIUM
    assert Confidence.parse("nonsense") == Confidence.MEDIUM  # safe default
    assert Confidence.parse(None) == Confidence.MEDIUM


def test_confidence_has_orderable_rank():
    # Domain ordering lives on the model, so callers can sort/compare without
    # re-encoding the order (e.g. picking the strongest hypothesis).
    assert Confidence.LOW.rank < Confidence.MEDIUM.rank < Confidence.HIGH.rank
    strongest = max([Confidence.LOW, Confidence.HIGH, Confidence.MEDIUM], key=lambda c: c.rank)
    assert strongest == Confidence.HIGH


def test_reasoning_object_defaults():
    r = ReasoningObject(claim="x", category=ReasoningCategory.FACT)
    assert r.confidence == Confidence.MEDIUM
    assert r.evidence == []


def test_hypothesis_has_required_honesty_fields():
    h = Hypothesis(statement="cause", supporting_evidence=["evt:e1"])
    # contradicting evidence + missing info are first-class (present, may be empty)
    assert h.contradicting_evidence == []
    assert h.missing_information == []
    assert h.status == "active"


# --- timeline -------------------------------------------------------------

def test_build_timeline_sorts_chronologically():
    events = ReplayAdapter().get_events()
    shuffled = list(reversed(events))
    timeline = build_timeline(shuffled)
    ts = [e.timestamp for e in timeline]
    assert ts == sorted(ts)


# --- evidence catalog -----------------------------------------------------

def test_evidence_catalog_covers_events_and_metrics():
    src = ReplayAdapter()
    catalog, context = build_evidence_catalog(src)
    # one entry per event and per (non-empty) metric
    assert "evt:e1" in catalog
    assert "met:api.latency.p95" in catalog
    assert catalog["met:api.latency.p95"].kind == "metric"
    assert catalog["evt:e1"].kind == "event"
    # context string lists ids so the model can cite them
    assert "met:api.latency.p95" in context
    assert "evt:e1" in context


# --- llm helpers ----------------------------------------------------------

def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced_with_prose():
    raw = 'Sure, here:\n```json\n{"a": 1, "b": [2,3]}\n```\nhope that helps'
    assert extract_json(raw) == {"a": 1, "b": [2, 3]}


def test_extract_json_raises_on_garbage():
    with pytest.raises(ValueError):
        extract_json("no json here at all")


def test_extract_json_raises_on_malformed_object():
    # A brace pair is found but the content isn't valid JSON.
    with pytest.raises(ValueError):
        extract_json("here: {a: 1, oops}")


def test_anthropic_client_selects_model_and_returns_text():
    calls = []

    class _Msgs:
        def create(self, **kw):
            calls.append(kw)
            return SimpleNamespace(content=[SimpleNamespace(text="hello ")
                                            , SimpleNamespace(text="world")])

    fake = SimpleNamespace(messages=_Msgs())
    c = AnthropicClient("key", model_fast="fast-m", model_deep="deep-m", client=fake)

    assert c.complete("sys", "usr", deep=True) == "hello world"
    assert calls[0]["model"] == "deep-m"
    c.complete("sys", "usr")
    assert calls[1]["model"] == "fast-m"


# --- Claude CLI client (the keyless "Claude Code" backend) ----------------

def test_claude_cli_client_invokes_cli_and_selects_model():
    seen = []

    def runner(cmd, timeout):
        seen.append(cmd)
        return "  reasoned answer\n"

    c = ClaudeCliClient(model_fast="fast-m", model_deep="deep-m", runner=runner)

    # returns trimmed stdout; no API key involved
    assert c.complete("sys", "usr", deep=True) == "reasoned answer"
    deep_cmd = seen[0]
    assert deep_cmd[0] == "claude"
    assert "-p" in deep_cmd and "usr" in deep_cmd          # user prompt passed
    assert "sys" in deep_cmd                                # system prompt passed
    assert "deep-m" in deep_cmd                             # deep selects deep model

    c.complete("sys", "usr")                                # fast path
    assert "fast-m" in seen[1]


def test_claude_cli_client_surfaces_runner_failure():
    def runner(cmd, timeout):
        raise RuntimeError("claude CLI failed (1): not logged in")

    with pytest.raises(RuntimeError):
        ClaudeCliClient("f", "d", runner=runner).complete("s", "u")


def test_default_runner_runs_a_real_process():
    # Uses the running Python as a stand-in CLI — portable, no network, no claude needed.
    out = _default_runner([sys.executable, "-c", "import sys; sys.stdout.write('ok')"], 30)
    assert out == "ok"


def test_default_runner_raises_on_nonzero_exit():
    with pytest.raises(RuntimeError):
        _default_runner([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"], 30)


def test_cli_available_is_a_bool():
    # Detection must never raise regardless of whether `claude` is installed.
    assert isinstance(cli_available(), bool)


# --- prompt hardening -----------------------------------------------------

def test_system_prompt_is_hardened_against_injection():
    from app.reasoning.engine import _SYSTEM
    low = _SYSTEM.lower()
    # the model is told to treat inputs as untrusted data, not instructions
    assert "untrusted" in low
    assert "instruction" in low


# --- engine ---------------------------------------------------------------

_CANNED = """```json
{
  "summary": "A deployment at 09:02 introduced a latency regression in checkout.",
  "facts": [
    {"claim": "API p95 latency spiked to ~480ms", "confidence": "high",
     "evidence": ["met:api.latency.p95", "evt:e5"]}
  ],
  "hypotheses": [
    {"statement": "The v2.4.1 deploy increased DB load via cache misses",
     "confidence": "high",
     "supporting_evidence": ["evt:e2", "met:cache.hit_ratio", "met:db.query.latency.p95"],
     "contradicting_evidence": [],
     "missing_information": ["Query-level DB traces"]}
  ],
  "recommendations": [
    {"claim": "Confirm recovery held after the rollback", "confidence": "medium",
     "evidence": ["evt:e8"]}
  ],
  "unknowns": [
    {"claim": "Whether any orders actually failed", "confidence": "low",
     "evidence": ["evt:nope"]}
  ]
}
```"""


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.last = None

    def complete(self, system, user, deep=False):
        self.last = {"system": system, "user": user, "deep": deep}
        return self.payload


def test_engine_produces_structured_grounded_investigation():
    src = ReplayAdapter()
    llm = FakeLLM(_CANNED)
    inv = ReasoningEngine(src, llm).investigate("Why is checkout slow?")

    assert inv.question == "Why is checkout slow?"
    assert inv.summary

    # categorized correctly
    assert inv.facts and inv.facts[0].category == ReasoningCategory.FACT
    assert inv.recommendations and inv.recommendations[0].category == ReasoningCategory.RECOMMENDATION
    assert inv.unknowns and inv.unknowns[0].category == ReasoningCategory.UNKNOWN

    # hypothesis is first-class with honesty fields populated
    h = inv.hypotheses[0]
    assert h.confidence == Confidence.HIGH
    assert h.missing_information
    assert all(ref in inv.evidence for ref in h.supporting_evidence)

    # every cited fact-evidence id resolves in the catalog
    assert all(ref in inv.evidence for ref in inv.facts[0].evidence)

    # invalid evidence ids are filtered out (grounding guarantee)
    assert inv.unknowns[0].evidence == []

    # timeline present and ordered
    assert inv.timeline == sorted(inv.timeline, key=lambda e: e.timestamp)

    # the deep model was used and the evidence catalog was sent to the model
    assert llm.last["deep"] is True
    assert "met:api.latency.p95" in llm.last["user"]


def test_engine_survives_non_json_response():
    src = ReplayAdapter()
    with pytest.raises(ValueError):
        ReasoningEngine(src, FakeLLM("I could not analyze this.")).investigate()


def test_engine_rejects_non_object_json():
    # A (fenced) JSON array is valid JSON but not the expected investigation
    # object — the engine must reject it rather than mis-assemble.
    src = ReplayAdapter()
    with pytest.raises(ValueError):
        ReasoningEngine(src, FakeLLM("```json\n[1, 2, 3]\n```")).investigate()


def test_engine_includes_conversation_history_in_prompt():
    """Follow-ups must carry context: prior turns are fed to the model so it can
    reason about 'what changed after that?' instead of starting cold."""
    src = ReplayAdapter()
    llm = FakeLLM(_CANNED)
    history = [
        ("user", "Is the system healthy?"),
        ("assistant", "Checkout latency spiked after the 09:02 deploy."),
    ]
    ReasoningEngine(src, llm).investigate("What changed after that?", history=history)
    prompt = llm.last["user"]
    assert "Is the system healthy?" in prompt
    assert "Checkout latency spiked after the 09:02 deploy." in prompt
    assert "What changed after that?" in prompt


def test_engine_history_is_optional_and_bounded():
    # No history => no transcript section; long history is trimmed to recent turns.
    src = ReplayAdapter()
    llm = FakeLLM(_CANNED)
    ReasoningEngine(src, llm).investigate("hello")
    assert "CONVERSATION SO FAR" not in llm.last["user"]

    long_history = [("user", f"q{i}") for i in range(20)]
    ReasoningEngine(src, llm, history_limit=4).investigate("now", history=long_history)
    assert "q19" in llm.last["user"]      # most recent kept
    assert "q0" not in llm.last["user"]    # oldest trimmed
