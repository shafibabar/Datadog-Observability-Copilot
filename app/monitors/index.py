"""Monitors index — knowledge extracted from the ec-conduct-dd-monitors Terraform repo.

Three things are extracted, all from a local checkout located via MONITORS_REPO_PATH
(empty/missing path → empty index, graceful):

  - **Monitors**: every `datadog_monitor` resource in `modules/*/main.tf`.
  - **Metric queries**: every in-scope timeseries query in monitor AND dashboard
    modules, normalized to plain adapter-ready queries (scope reset to `{*}` —
    the Datadog adapter rewrites that block from the investigation Scope —
    grouping dropped, `.as_count()/.as_rate()` preserved). Which metric
    namespaces count as in-scope comes from DATADOG_METRIC_NAMESPACES
    (default `ec.`); see app/telemetry/namespaces.py.
  - **Vocabulary aliases**: human phrases ("message processing", "quota manager")
    → the metric names they refer to, derived from module names and metric name
    segments. The resolver uses this to map user terms to real telemetry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.telemetry.namespaces import parse_patterns, prefixes


@dataclass
class Monitor:
    """A single monitor definition extracted from Terraform."""

    name: str
    module: str
    description: str = ""
    query_metric: str = ""
    alert_channels: list[str] | None = None


@dataclass
class Dashboard:
    """A dashboard definition."""

    name: str
    url: str
    description: str = ""


@dataclass
class MonitorsIndex:
    """Structured index of monitors, dashboards, metric queries, and vocabulary."""

    monitors: list[Monitor]
    dashboards: list[Dashboard]
    repo_path: str
    #: {metric_name: normalized datadog query, e.g. "sum:ec.x.y{*}.as_count()"}
    metric_queries: dict[str, str] = field(default_factory=dict)
    #: {lowercase alias phrase: sorted metric names it refers to}
    aliases: dict[str, list[str]] = field(default_factory=dict)


# The metric namespace scanned when nothing is configured — the original behavior.
_DEFAULT_PREFIXES = ("ec.",)


def _namespace_alternation(namespaces: tuple[str, ...]) -> str:
    """A regex alternation of the in-scope metric prefixes, e.g. `(?:ec\\.|ea\\.)`.

    Built from DATADOG_METRIC_NAMESPACES so the extractor scans exactly the
    namespaces the copilot is scoped to; unset falls back to `ec.`.
    """
    heads = prefixes(parse_patterns(namespaces)) or _DEFAULT_PREFIXES
    return "(?:" + "|".join(re.escape(h) for h in heads) + ")"


def _query_re(namespaces: tuple[str, ...]) -> re.Pattern[str]:
    """agg:<ns>.metric{scope} [by {...}] [.as_count()/.as_rate()] — the scope block
    may contain Terraform interpolations (`${env.name}`), which contain `}`."""
    return re.compile(
        r"\b(sum|avg|min|max):(" + _namespace_alternation(namespaces) + r"[a-z0-9_.]+)"
        r"\{(?:\$\{[^}]*\}|[^{}])*\}"
        r"(?:\s*by\s*\{[^}]*\})?"
        r"((?:\.as_(?:count|rate)\(\))?)"
    )


def build_monitors_index(repo_path: str = "", namespaces: tuple[str, ...] = ()) -> MonitorsIndex:
    """Scan the Terraform repo and build the full index.

    The path is machine-specific and comes from MONITORS_REPO_PATH (see
    app.config); an empty or missing path yields an empty index so the app
    degrades gracefully rather than crashing. `namespaces` is the configured
    metric scope (DATADOG_METRIC_NAMESPACES); empty means the `ec.` default.
    """
    if not repo_path:
        return MonitorsIndex(monitors=[], dashboards=[], repo_path="")
    repo = Path(repo_path)
    if not repo.exists():
        return MonitorsIndex(monitors=[], dashboards=[], repo_path=repo_path)

    monitors = _extract_monitors(repo, namespaces)
    dashboards = _extract_dashboards(repo)
    metric_queries, aliases = _extract_metric_queries(repo, namespaces)

    return MonitorsIndex(
        monitors=sorted(monitors, key=lambda m: m.name),
        dashboards=sorted(dashboards, key=lambda d: d.name),
        repo_path=str(repo),
        metric_queries=metric_queries,
        aliases=aliases,
    )


def _module_alias(module_name: str, namespaces: tuple[str, ...] = ()) -> str:
    """A human phrase for a module: ec_message_processing_summary_dashboard →
    'message processing'. The leading namespace ("ec_", "ea_") is stripped so the
    alias is what a person would actually type."""
    name = module_name
    heads = prefixes(parse_patterns(namespaces)) or _DEFAULT_PREFIXES
    for head in heads:
        name = name.removeprefix(head.rstrip(".") + "_")
    for suffix in ("_dashboard", "_summary", "_apis"):
        while name.endswith(suffix):
            name = name.removesuffix(suffix)
    return name.replace("_", " ").strip()


def _service_aliases(metric_name: str) -> list[str]:
    """Alias phrases from a metric's service segment: ec.surveillance_policy_evaluator.x
    → ['surveillance policy evaluator', 'policy evaluator']."""
    parts = metric_name.split(".")
    if len(parts) < 2:
        return []
    segment = parts[1]
    aliases = [segment.replace("_", " ")]
    if segment.startswith("surveillance_"):
        aliases.append(segment.removeprefix("surveillance_").replace("_", " "))
    return aliases


#: Shortest service phrase safe to treat as guard vocabulary. The guard matches
#: these as plain SUBSTRINGS, so a 1-2 character segment (e.g. "ec.a.b" -> "a")
#: would appear in almost every message and fast-allow everything — disabling the
#: very gate it was meant to inform.
MIN_VOCABULARY_LEN = 4


def aliases_from_metric_names(metric_names) -> dict[str, list[str]]:
    """Build an alias-phrase -> metrics map from metric names alone.

    The Terraform repo is the *richer* source of vocabulary (module names give
    phrases like "message processing" that no metric name contains), but it is
    optional: with MONITORS_REPO_PATH unset, live discovery still yields hundreds
    of metrics, and the resolver needs something to match questions against.
    "ec.alerting_service.alert_published_counter" -> {"alerting service": [...]}.
    """
    out: dict[str, list[str]] = {}
    for name in sorted(metric_names):
        for alias in _service_aliases(name):
            if len(alias) >= MIN_VOCABULARY_LEN:
                out.setdefault(alias, []).append(name)
    return out


def service_vocabulary(metric_names: list[str]) -> tuple[str, ...]:
    """The human service phrases implied by a set of metric names.

    ["ec.quota_manager.pipeline_processed_counter"] -> ("quota manager",). Used to
    teach the relevance guard the platform's own service names straight from the
    in-scope metric registry, so no one has to list them by hand.
    """
    return tuple(sorted({
        alias for name in metric_names for alias in _service_aliases(name)
        if len(alias) >= MIN_VOCABULARY_LEN
    }))


def _extract_metric_queries(
    repo: Path, namespaces: tuple[str, ...] = ()
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Extract normalized in-scope metric queries and the alias→metrics vocabulary
    from every .tf file under modules/."""
    queries: dict[str, str] = {}
    alias_sets: dict[str, set[str]] = {}

    modules_dir = repo / "modules"
    if not modules_dir.exists():
        return queries, {}

    query_re = _query_re(namespaces)
    for tf_file in sorted(modules_dir.glob("*/*.tf")):
        content = tf_file.read_text()
        module_alias = _module_alias(tf_file.parent.name, namespaces)
        for agg, metric, suffix in query_re.findall(content):
            queries.setdefault(metric, f"{agg}:{metric}{{*}}{suffix}")
            alias_sets.setdefault(module_alias, set()).add(metric)
            for alias in _service_aliases(metric):
                alias_sets.setdefault(alias, set()).add(metric)

    aliases = {a: sorted(metrics) for a, metrics in sorted(alias_sets.items()) if a}
    return queries, aliases


def _extract_monitors(repo: Path, namespaces: tuple[str, ...] = ()) -> list[Monitor]:
    """Extract all monitor definitions from module main.tf files."""
    monitors: list[Monitor] = []
    modules_dir = repo / "modules"

    if not modules_dir.exists():
        return monitors

    metric_re = re.compile("(" + _namespace_alternation(namespaces) + "[a-z0-9_.]+)")

    for module_dir in sorted(modules_dir.iterdir()):
        if not module_dir.is_dir():
            continue

        main_tf = module_dir / "main.tf"
        if not main_tf.exists():
            continue

        content = main_tf.read_text()
        module_name = module_dir.name

        monitor_blocks = re.findall(
            r'resource\s+"datadog_monitor"\s+"([^"]+)"',
            content,
        )
        metrics = metric_re.findall(content)
        channels = re.findall(r"alert_channel[_\w]*", content)

        for resource_id in monitor_blocks:
            # The per-module DOCS.md files are tf-docs boilerplate (tables, no
            # prose), so the module name itself is the best description we have.
            monitors.append(Monitor(
                name=module_name,
                module=resource_id,
                description=module_name.replace("_", " "),
                query_metric=metrics[0] if metrics else "",
                alert_channels=list(set(channels)) if channels else None,
            ))

    return monitors


def _extract_dashboards(repo: Path) -> list[Dashboard]:
    """Extract dashboard definitions from dashboards directory or variable references."""
    dashboards: list[Dashboard] = []
    dashboards_dir = repo / "dashboards"

    if not dashboards_dir.exists():
        return dashboards

    main_tf = dashboards_dir / "main.tf"
    if main_tf.exists():
        content = main_tf.read_text()
        dashboard_resources = re.findall(
            r'resource\s+"datadog_dashboard"\s+"([^"]+)"\s+{[^}]*title\s*=\s*"([^"]+)"',
            content,
            re.DOTALL,
        )
        for resource_id, title in dashboard_resources:
            dashboards.append(Dashboard(
                name=resource_id, url=f"dashboards/{resource_id}", description=title,
            ))

    root_main_tf = repo / "main.tf"
    if root_main_tf.exists():
        content = root_main_tf.read_text()
        dashboard_refs = re.findall(r"dashboard_url\s*=\s*var\.dashboards\.(\w+)", content)
        for ref in dashboard_refs:
            if not any(d.name == ref for d in dashboards):
                dashboards.append(Dashboard(
                    name=ref, url=f"dashboards/{ref}",
                    description=f"Datadog dashboard: {ref}",
                ))

    return dashboards


def get_monitors_context(index: MonitorsIndex) -> str:
    """Format the index as contextual information for the reasoning prompt.

    Includes the monitor list, dashboards, and the service vocabulary (alias →
    how many metrics it covers). The raw metric-query map is deliberately NOT
    included — selected metrics enter the prompt as real evidence entries.
    """
    if not index.monitors and not index.dashboards:
        return ""

    lines = ["## Configured Monitors & Dashboards\n"]

    if index.monitors:
        lines.append(f"### Monitors ({len(index.monitors)} total)\n")
        for monitor in index.monitors:
            metric = f" — metric: `{monitor.query_metric}`" if monitor.query_metric else ""
            lines.append(f"- **{monitor.name}**{metric}")
        lines.append("")

    if index.dashboards:
        lines.append(f"### Dashboards ({len(index.dashboards)} total)\n")
        for dashboard in index.dashboards:
            lines.append(f"- **{dashboard.name}**: {dashboard.description}")
        lines.append("")

    if index.aliases:
        lines.append("### Known services (telemetry available on request)\n")
        for alias, metrics in index.aliases.items():
            lines.append(f"- {alias} ({len(metrics)} metrics)")
        lines.append("")

    return "\n".join(lines)
