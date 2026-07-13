"""Domain knowledge about the EC observability system.

This module encodes what the copilot knows about the system architecture,
services, typical metrics, and failure modes so it can reason effectively
about incidents and telemetry.
"""
from __future__ import annotations


# Services in the system and what they do
SERVICES = {
    "message_processing": "Processes incoming messages, handles routing and distribution",
    "debezium": "Captures change data from sources using CDC connectors",
    "quota_manager": "Manages quota allocations and consumption tracking",
    "config_curator": "Manages system configuration and deployment of config changes",
    "policy_evaluator": "Evaluates policies and applies policy decisions",
    "indexer": "Indexes documents and manages search/retrieval",
    "lookback": "Handles lookback processing and backfill operations",
    "surveillance_filter": "Filters and routes surveillance data",
    "review_service": "Manages review workflows and decisions",
    "gateway": "API gateway and request routing",
}

# Typical metrics per service
TYPICAL_METRICS = {
    "latency": "Response time (p50, p95, p99), processing time",
    "errors": "Error rate, exception count, 5xx responses",
    "throughput": "Requests/messages per second, queue depth",
    "resources": "CPU, memory, disk usage",
    "cache": "Cache hit ratio, cache eviction rate",
    "database": "Query latency, connection pool usage, transaction time",
    "queue": "Consumer lag, queue depth, backlog",
    "dlt": "Dead letter topic count, failed message count",
}

# Common failure modes
FAILURE_MODES = {
    "deployment": "New version introduced bug, performance regression, or incompatibility",
    "cache_invalidation": "Cache miss spike, hit ratio drop, increased latency",
    "database": "Connection pool exhausted, query slowdown, index missing",
    "queue_backlog": "Consumer lag increasing, messages not being processed",
    "resource_exhaustion": "CPU/memory peaked, causing throttling or OOM",
    "downstream_dependency": "Called service is slow/failing, causing cascading failure",
    "config_change": "Configuration change broke service or introduced invalid state",
}

# Environments
ENVIRONMENTS = ["prod", "non-prod", "staging", "dev"]

# Tenants (example — typically customer namespaces)
TYPICAL_TENANTS = ["acme", "contoso", "customer-x"]


def get_domain_context() -> str:
    """Build a domain knowledge summary for injection into the system prompt.

    This is appended to the system prompt so the model understands the
    observability context, the services, and typical issues.
    """
    lines = [
        "## EC System Knowledge Base",
        "",
        "### Services",
        "The EC system comprises these core services:",
    ]

    for service, description in SERVICES.items():
        lines.append(f"- **{service}**: {description}")

    lines.extend([
        "",
        "### Typical Metrics to Investigate",
        "When investigating any service, consider these metric categories:",
    ])

    for category, description in TYPICAL_METRICS.items():
        lines.append(f"- **{category}**: {description}")

    lines.extend([
        "",
        "### Common Failure Modes",
        "Incidents often result from these patterns:",
    ])

    for mode, description in FAILURE_MODES.items():
        lines.append(f"- **{mode}**: {description}")

    lines.extend([
        "",
        "### Scope Context",
        f"- Environments: {', '.join(ENVIRONMENTS)}",
        f"- Typical tenants: {', '.join(TYPICAL_TENANTS)}",
        "- Time window: bounded to 7 days max per scope",
        "",
        "### Investigation Approach",
        "1. Establish timeline: when did the issue start?",
        "2. Identify scope: which service(s), environment(s), tenant(s)?",
        "3. Find correlation: which metrics/events moved together?",
        "4. Form hypothesis: what change (deploy, config, downstream) preceded it?",
        "5. Test hypothesis: what evidence supports/contradicts it?",
        "6. Recommend: what's the immediate fix? What should we investigate?",
    ])

    return "\n".join(lines)
