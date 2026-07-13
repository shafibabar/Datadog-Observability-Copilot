"""Tests for the monitors knowledge base integration."""
import pytest

from app.monitors.index import build_monitors_index, get_monitors_context


def test_build_monitors_index():
    """Verify monitors index builds from the Terraform repo."""
    index = build_monitors_index()
    assert index is not None
    assert index.repo_path == "/Users/shafibabar/SmarshGitRepos/ec-conduct-dd-monitors"
    # The repo should have monitors and dashboards
    assert len(index.monitors) > 0 or len(index.dashboards) > 0


def test_monitors_index_structure():
    """Verify monitors have expected attributes."""
    index = build_monitors_index()
    if index.monitors:
        monitor = index.monitors[0]
        assert hasattr(monitor, "name")
        assert hasattr(monitor, "module")
        assert hasattr(monitor, "description")


def test_dashboards_index_structure():
    """Verify dashboards have expected attributes."""
    index = build_monitors_index()
    if index.dashboards:
        dashboard = index.dashboards[0]
        assert hasattr(dashboard, "name")
        assert hasattr(dashboard, "url")


def test_get_monitors_context():
    """Verify monitors context formatting."""
    index = build_monitors_index()
    context = get_monitors_context(index)
    if index.monitors or index.dashboards:
        assert "Configured Monitors" in context or "Dashboards" in context


def test_empty_monitors_context():
    """Verify empty index returns empty context."""
    from app.monitors.index import MonitorsIndex

    empty_index = MonitorsIndex(monitors=[], dashboards=[], repo_path="")
    context = get_monitors_context(empty_index)
    assert context == ""
