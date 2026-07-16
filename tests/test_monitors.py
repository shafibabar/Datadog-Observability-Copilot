"""Tests for the monitors knowledge base (Terraform repo index).

The index is exercised against a small fixture Terraform tree written to
tmp_path — never against a real checkout — so the suite stays green on any
machine regardless of whether ec-conduct-dd-monitors is present locally.
"""
from pathlib import Path

from app.monitors.index import MonitorsIndex, build_monitors_index, get_monitors_context

_MODULE_TF = '''
terraform {
  required_providers {
    datadog = { source = "DataDog/datadog", version = "3.79.0" }
  }
}

resource "datadog_monitor" "audit_event_consumer_failure" {
  for_each = local.query
  name     = "Audit Communication Event Consumer Failure for ${each.key}"
  type     = "query alert"
  query    = "sum(last_5m):sum:ec.centralised_audit.communication_event_dlt_counter{kube_namespace:${env.name}} by {exception,tenant}.as_count() > 0"
  message  = "alert_channel_p1"
}
'''

_ROOT_TF = '''
module "audit_event_consumer_failure" {
  source        = "./modules/audit_event_consumer_failure"
  dashboard_url = var.dashboards.audit
}
'''


def _write_fixture_repo(root: Path) -> Path:
    module_dir = root / "modules" / "audit_event_consumer_failure"
    module_dir.mkdir(parents=True)
    (module_dir / "main.tf").write_text(_MODULE_TF)
    (root / "main.tf").write_text('dashboard_url = var.dashboards.audit\n')
    dashboards = root / "dashboards"
    dashboards.mkdir()
    (dashboards / "main.tf").write_text("")
    return root


def test_empty_path_yields_empty_index():
    index = build_monitors_index("")
    assert index.monitors == [] and index.dashboards == []


def test_missing_path_yields_empty_index(tmp_path):
    index = build_monitors_index(str(tmp_path / "does-not-exist"))
    assert index.monitors == [] and index.dashboards == []


def test_monitors_extracted_from_fixture_repo(tmp_path):
    repo = _write_fixture_repo(tmp_path)
    index = build_monitors_index(str(repo))
    assert len(index.monitors) == 1
    monitor = index.monitors[0]
    assert monitor.name == "audit_event_consumer_failure"
    assert monitor.module == "audit_event_consumer_failure"
    assert monitor.query_metric.startswith("ec.centralised_audit.")


def test_dashboards_extracted_from_root_variable_refs(tmp_path):
    repo = _write_fixture_repo(tmp_path)
    index = build_monitors_index(str(repo))
    assert [d.name for d in index.dashboards] == ["audit"]


def test_context_formats_monitors_and_dashboards(tmp_path):
    repo = _write_fixture_repo(tmp_path)
    context = get_monitors_context(build_monitors_index(str(repo)))
    assert "Configured Monitors" in context
    assert "audit_event_consumer_failure" in context
    assert "ec.centralised_audit.communication_event_dlt_counter" in context


def test_empty_index_formats_to_empty_context():
    empty = MonitorsIndex(monitors=[], dashboards=[], repo_path="")
    assert get_monitors_context(empty) == ""
