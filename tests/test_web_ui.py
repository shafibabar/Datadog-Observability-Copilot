"""Declarative UI-contract tests for the product web UI (app/web).

The offline suite can't execute JS, so — per the project lesson "don't mark UI
behaviour manual-smoke-only" — we lock the *structural* contract of the scope/UX
feature against the served markup + static assets: a scope control row below the
composer (Environment · Tenant · Duration · Explain-as), the persona selector and
the old workspace icon gone from the header, resizable/collapsible panels, a copy
button per reply, and send gated on a valid scope.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _html() -> str:
    return client.get("/").text


def _js() -> str:
    return client.get("/static/app.js").text


def test_scope_menu_below_the_composer():
    html = _html()
    assert 'id="scope-trigger"' in html and 'id="scope-panel"' in html
    assert html.index('id="composer"') < html.index('id="controls"')


def test_scope_menu_offers_all_four_categories_with_drilldown():
    js = _js()
    for category in ("Environment", "Tenant", "Duration", "Explain as"):
        assert category in js
    assert "scope-row" in js and "scope-opt" in js    # drill-down category rows + option rows


def test_persona_selector_moved_out_of_header_into_controls():
    html = _html()
    assert 'id="persona"' in html
    header = html[html.index('class="topbar"'):html.index('id="chat"')]
    assert 'id="persona"' not in header          # no longer in the header
    # and it sits inside the control row, after the composer
    assert html.index('id="composer"') < html.index('id="persona"')


def test_old_workspace_toggle_icon_removed_from_header():
    html = _html()
    assert 'id="toggle-workspace"' not in html
    assert "⧉" not in html


def test_panels_are_resizable_and_collapsible():
    html = _html()
    for el in ("resize-left", "resize-right", "collapse-left", "collapse-right"):
        assert el in html


def test_each_reply_gets_a_copy_button():
    js = _js()
    assert "navigator.clipboard" in js
    assert "copy-btn" in js


def test_send_is_gated_on_a_valid_scope():
    assert "scopeValid" in _js()


def test_duration_offers_presets_and_a_custom_range():
    combined = _html() + _js()
    assert "Last 1 hour" in combined
    assert "Last 1 week" in combined
    assert "custom" in combined.lower()


def test_scopes_are_fetched_and_env_tenant_multiselects_present():
    js = _js()
    assert "/api/scopes" in js
    assert "environments" in js and "tenants" in js


def test_conversations_can_be_renamed_and_deleted():
    js = _js()
    assert "PATCH" in js and "DELETE" in js


def test_assets_are_cache_busted_to_prevent_stale_styles():
    # New HTML must never be styled by a stale cached stylesheet/script.
    html = _html()
    assert "/static/styles.css?v=" in html
    assert "/static/app.js?v=" in html
    r = client.get("/")
    assert "no-store" in r.headers.get("cache-control", "")
