"""Semantic relevance classifier for Stage 2 of the guard.

Uses the LLM to make a semantic judgment about whether a message is genuinely
about system health, telemetry, and incidents — vs off-topic. This runs only
on the ambiguous middle (questions that didn't trigger keywords but aren't
clearly off-topic), so cost is bounded.
"""
from __future__ import annotations

# System prompt for the classifier: very cheap, yes/no only, no explanation needed
_CLASSIFIER_SYSTEM = (
    "You are a relevance classifier for an observability/incident investigation system. "
    "Determine if a message is about system health, telemetry, performance, incidents, or operations. "
    "Respond with ONLY 'yes' or 'no' (lowercase, no punctuation). "
    "\n"
    "You understand these domains:\n"
    "- System performance: latency, errors, throughput, CPU, memory, disk usage\n"
    "- Incidents: outages, degradations, anomalies, root causes\n"
    "- Services: message processing, debezium, quota manager, config curator, policy evaluator, indexer\n"
    "- Operations: deployments, rollbacks, infrastructure changes, monitoring\n"
    "- Queue systems: consumer lag, dead letter topics, backlog, processing delays\n"
    "\n"
    "Reject: general knowledge, world events, coding questions, unrelated topics.\n"
    "Accept: any question about system health, telemetry, incidents, or operations."
)


def classify_relevance(text: str, llm_client=None) -> bool:
    """Classify if a message is relevant to observability/incidents.

    Args:
        text: The user message to classify
        llm_client: LLMClient instance (e.g., AnthropicClient or ClaudeCliClient)

    Returns:
        True if relevant, False otherwise. Returns True on error (fail open for legitimate issues).
    """
    if not llm_client or not text:
        return True  # Default to allow if no classifier available

    try:
        response = llm_client.complete(
            system=_CLASSIFIER_SYSTEM,
            prompt=f"Is this about system health, telemetry, or incidents?\n\n{text}",
            deep=False,  # Use fast model for speed
        )
        result = response.strip().lower()
        return result.startswith("yes")
    except Exception:
        # Fail open: if classifier fails, allow the message through
        # (better to let ambiguous messages through than block legitimate ones)
        return True
