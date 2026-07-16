"""General SRE investigation knowledge injected into the reasoning system prompt.

Deliberately contains ONLY provider- and org-agnostic method knowledge (metric
categories, failure patterns, investigation discipline). Org-specific ground
truth — which services exist, which monitors are configured, which metrics they
watch — comes from the monitors index (app.monitors) and the live evidence
catalog, never from hand-written constants here: inventing services or tenants
in the prompt would seed the model with fiction it could present as fact.
"""
from __future__ import annotations

# Metric categories worth considering for any service under investigation.
METRIC_CATEGORIES = {
    "latency": "Response time (p50, p95, p99), processing time",
    "errors": "Error rate, exception count, 5xx responses",
    "throughput": "Requests/messages per second, queue depth",
    "resources": "CPU, memory, disk usage",
    "cache": "Cache hit ratio, cache eviction rate",
    "database": "Query latency, connection pool usage, transaction time",
    "queue": "Consumer lag, queue depth, backlog",
    "dlt": "Dead letter topic count, failed message count",
}

# Failure patterns that commonly explain incidents.
FAILURE_MODES = {
    "deployment": "New version introduced bug, performance regression, or incompatibility",
    "cache_invalidation": "Cache miss spike, hit ratio drop, increased latency",
    "database": "Connection pool exhausted, query slowdown, index missing",
    "queue_backlog": "Consumer lag increasing, messages not being processed",
    "resource_exhaustion": "CPU/memory peaked, causing throttling or OOM",
    "downstream_dependency": "Called service is slow/failing, causing cascading failure",
    "config_change": "Configuration change broke service or introduced invalid state",
}


def get_domain_context() -> str:
    """Build the method-knowledge block for the reasoning system prompt."""
    lines = [
        "## Investigation Method",
        "",
        "### Metric Categories to Consider",
    ]
    for category, description in METRIC_CATEGORIES.items():
        lines.append(f"- **{category}**: {description}")

    lines.extend(["", "### Common Failure Modes"])
    for mode, description in FAILURE_MODES.items():
        lines.append(f"- **{mode}**: {description}")

    lines.extend([
        "",
        "### Approach",
        "1. Establish timeline: when did the issue start?",
        "2. Identify scope: which service(s), environment(s), tenant(s)?",
        "3. Find correlation: which metrics/events moved together?",
        "4. Form hypothesis: what change (deploy, config, downstream) preceded it?",
        "5. Test hypothesis: what evidence supports/contradicts it?",
        "6. Recommend: what's the immediate fix? What should we investigate?",
        "",
        "Ground every service-specific claim in the evidence catalog and the",
        "configured-monitors list; if telemetry for a named service is not in the",
        "catalog, say so as an Unknown rather than inventing plausible numbers.",
    ])
    return "\n".join(lines)
