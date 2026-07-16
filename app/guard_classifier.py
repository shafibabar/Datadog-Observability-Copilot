"""Semantic relevance classifier for Stage 2 of the guard.

Uses the LLM to make a semantic judgment about whether a message is genuinely
about system health, telemetry, and incidents — vs off-topic. This runs only on
the ambiguous middle (messages Stage 1 neither fast-allowed nor blocked), so
cost is bounded.

Failure semantics: exceptions are deliberately NOT caught here. `guard.evaluate`
owns the failure policy — a classifier that raises counts as "refuse" (fail
closed), per the guard's documented contract. Swallowing errors here would
silently invert that policy.
"""
from __future__ import annotations

# System prompt for the classifier: cheap, yes/no only, fast model.
_CLASSIFIER_SYSTEM = (
    "You are a relevance classifier for an observability/incident investigation system. "
    "Determine if a message is about system health, telemetry, performance, incidents, "
    "or operations — including short conversational follow-ups within such a discussion. "
    "Respond with ONLY 'yes' or 'no' (lowercase, no punctuation).\n"
    "\n"
    "In scope: system performance (latency, errors, throughput, resources); incidents "
    "(outages, degradations, root causes); services and their processing pipelines "
    "(queues, consumers, lag, dead-letter topics); deployments and infrastructure; "
    "monitoring and alerting configuration.\n"
    "Out of scope: general knowledge, world events, life advice, coding help, or any "
    "other topic unrelated to operating a software system."
)


def classify_relevance(text: str, llm_client) -> bool:
    """Return True when `text` is a genuine observability/operations message.

    `llm_client` is any LLMClient (AnthropicClient or ClaudeCliClient). Errors
    propagate to the caller — see the module docstring for why.
    """
    response = llm_client.complete(
        system=_CLASSIFIER_SYSTEM,
        prompt=f"Is this about system health, telemetry, or incidents?\n\n{text}",
        deep=False,  # fast model: this is a yes/no gate, not reasoning
    )
    return response.strip().lower().startswith("yes")
