"""Monitors index builder — scans Terraform repo for monitors and dashboards.

Extracts monitor definitions, alert queries, and dashboard URLs from the
ec-conduct-dd-monitors repo to provide context to the reasoning engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


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
    """Structured index of all monitors and dashboards."""

    monitors: list[Monitor]
    dashboards: list[Dashboard]
    repo_path: str


def build_monitors_index(
    repo_path: str = "/Users/shafibabar/SmarshGitRepos/ec-conduct-dd-monitors",
) -> MonitorsIndex:
    """Scan the Terraform repo and build an index of monitors and dashboards.

    Returns a structured index that can be used for context enrichment.
    """
    repo = Path(repo_path)
    if not repo.exists():
        return MonitorsIndex(monitors=[], dashboards=[], repo_path=repo_path)

    monitors = _extract_monitors(repo)
    dashboards = _extract_dashboards(repo)

    return MonitorsIndex(
        monitors=sorted(monitors, key=lambda m: m.name),
        dashboards=sorted(dashboards, key=lambda d: d.name),
        repo_path=str(repo),
    )


def _extract_monitors(repo: Path) -> list[Monitor]:
    """Extract all monitor definitions from module main.tf files."""
    monitors: list[Monitor] = []
    modules_dir = repo / "modules"

    if not modules_dir.exists():
        return monitors

    for module_dir in sorted(modules_dir.iterdir()):
        if not module_dir.is_dir():
            continue

        main_tf = module_dir / "main.tf"
        if not main_tf.exists():
            continue

        content = main_tf.read_text()
        module_name = module_dir.name

        # Extract datadog_monitor resource definitions and their names/queries
        # Pattern: resource "datadog_monitor" "..." { name = "...", query = "..." }
        monitor_blocks = re.findall(
            r'resource\s+"datadog_monitor"\s+"([^"]+)"',
            content,
        )

        # Extract metric names from queries (e.g., ec.service.metric)
        metric_pattern = r"(ec\.[a-z0-9_.]+)"
        metrics = re.findall(metric_pattern, content)

        # Extract alert channel references
        channels = re.findall(r"alert_channel[_\w]*", content)

        for resource_id in monitor_blocks:
            # Read DOCS.md if available for better description
            docs_file = module_dir / "DOCS.md"
            description = ""
            if docs_file.exists():
                desc_content = docs_file.read_text()
                # Extract first non-markdown line as description
                lines = [
                    l.strip()
                    for l in desc_content.split("\n")
                    if l.strip() and not l.strip().startswith(("#", "<!--", "-"))
                ]
                if lines:
                    description = lines[0]

            monitor = Monitor(
                name=module_name,
                module=resource_id,
                description=description or f"Monitor for {module_name}",
                query_metric=metrics[0] if metrics else "",
                alert_channels=list(set(channels)) if channels else None,
            )
            monitors.append(monitor)

    return monitors


def _extract_dashboards(repo: Path) -> list[Dashboard]:
    """Extract dashboard definitions from dashboards directory or variable definitions."""
    dashboards: list[Dashboard] = []
    dashboards_dir = repo / "dashboards"

    if not dashboards_dir.exists():
        return dashboards

    # Check for dashboards defined in main.tf (as resource definitions)
    main_tf = dashboards_dir / "main.tf"
    if main_tf.exists():
        content = main_tf.read_text()
        # Extract datadog_dashboard resource definitions
        dashboard_resources = re.findall(
            r'resource\s+"datadog_dashboard"\s+"([^"]+)"\s+{[^}]*title\s*=\s*"([^"]+)"',
            content,
            re.DOTALL,
        )
        for resource_id, title in dashboard_resources:
            dashboard = Dashboard(
                name=resource_id,
                url=f"dashboards/{resource_id}",
                description=title,
            )
            dashboards.append(dashboard)

    # Also check for dashboard variable references in main.tf at root
    root_main_tf = repo / "main.tf"
    if root_main_tf.exists():
        content = root_main_tf.read_text()
        # Extract dashboard variable references (e.g., var.dashboards.audit)
        dashboard_refs = re.findall(
            r'dashboard_url\s*=\s*var\.dashboards\.(\w+)',
            content,
        )
        for ref in dashboard_refs:
            if not any(d.name == ref for d in dashboards):
                dashboard = Dashboard(
                    name=ref,
                    url=f"dashboards/{ref}",
                    description=f"Datadog dashboard: {ref}",
                )
                dashboards.append(dashboard)

    return dashboards


def get_monitors_context(index: MonitorsIndex) -> str:
    """Format the monitors index as contextual information for the reasoning engine.

    Returns a concise summary suitable for inclusion in system prompts.
    """
    if not index.monitors and not index.dashboards:
        return ""

    lines = ["## Configured Monitors & Dashboards\n"]

    if index.monitors:
        lines.append(f"### Monitors ({len(index.monitors)} total)\n")
        for monitor in index.monitors[:15]:  # Limit to avoid token bloat
            desc = monitor.description or monitor.name
            metric = f" [{monitor.query_metric}]" if monitor.query_metric else ""
            lines.append(f"- **{monitor.name}**{metric}: {desc}")
        if len(index.monitors) > 15:
            lines.append(f"- ... and {len(index.monitors) - 15} more monitors")
        lines.append("")

    if index.dashboards:
        lines.append(f"### Dashboards ({len(index.dashboards)} total)\n")
        for dashboard in index.dashboards:
            lines.append(f"- **{dashboard.name}**: {dashboard.description}")
        lines.append("")

    return "\n".join(lines)
