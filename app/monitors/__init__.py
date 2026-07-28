"""Monitors knowledge base — integration with ec-conduct-dd-monitors Terraform repo.

Provides a structured index of all configured monitors and dashboards so the
Copilot can understand what alerting is in place and answer configuration questions.
"""
from .index import build_monitors_index, get_monitors_context

__all__ = ["build_monitors_index", "get_monitors_context"]
