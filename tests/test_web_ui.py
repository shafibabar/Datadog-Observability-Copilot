"""Declarative UI-contract tests for the product web UI (app/web).

The offline suite can't execute JS, so — per the project lesson "don't mark UI
behaviour manual-smoke-only" — we lock the *structural* contract of the composer
+ @ scope-menu feature against the served markup + static assets: the old
mandatory scope-picker panel is gone, the composer is a contenteditable that
accepts inline locked chips inserted by a caret-anchored "@" menu, persona
stays a plain visible control, and sending no longer requires any scope.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _html() -> str:
    return client.get("/").text


def _js() -> str:
    return client.get("/static/app.js").text


def test_old_scope_picker_panel_is_gone():
    html = _html()
    assert 'id="scope-trigger"' not in html
    assert 'id="scope-panel"' not in html
    assert 'id="duration-select"' not in html


def test_composer_is_contenteditable_not_a_textarea():
    html = _html()
    assert '<textarea id="input"' not in html
    composer = html[html.index('id="composer"'):html.index('id="send"')]
    assert 'id="input"' in composer and 'contenteditable="true"' in composer


def test_at_menu_present_below_the_composer():
    html = _html()
    assert 'id="at-menu"' in html
    assert html.index('id="composer"') < html.index('id="at-menu"')


def test_at_menu_offers_environment_tenant_and_duration():
    js = _js()
    for category in ("Environment", "Tenant", "Duration"):
        assert category in js
    assert "scope-list" in js and "scope-opt" in js   # reused drill-down row/option styling


def test_at_sign_in_the_composer_triggers_the_menu():
    js = _js()
    assert 'e.data === "@"' in js
    assert "openAtMenu" in js


def test_selections_insert_locked_non_editable_chips():
    js = _js()
    assert "insertChip" in js
    assert 'chip.contentEditable = "false"' in js
    assert "chip-remove" in js   # explicit remove control, not text-editing


def test_scope_is_never_parsed_back_out_of_free_text():
    js = _js()
    # The message sent is built by skipping chip nodes, not by parsing chip data
    # out of the composer's text content.
    assert "composerText" in js
    assert 'classList.contains("scope-chip")' in js


def test_persona_selector_is_a_plain_visible_control_outside_the_header():
    html = _html()
    assert 'id="persona"' in html
    assert 'class="persona-select"' in html
    header = html[html.index('class="topbar"'):html.index('id="chat"')]
    assert 'id="persona"' not in header
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


def test_send_no_longer_requires_any_scope_selection():
    js = _js()
    # The old hard gate is gone; sending is only blocked on configured/currentId/busy.
    assert "Select at least one environment or tenant" not in js
    assert "scopePayload" in js


def test_duration_offers_presets_and_a_custom_range():
    combined = _html() + _js()
    assert "Last 1 hour" in combined
    assert "Last 1 week" in combined
    assert "custom" in combined.lower()


def test_scopes_are_fetched_for_the_at_menus_option_lists():
    js = _js()
    assert "/api/scopes" in js
    assert "envOptions" in js and "tenantOptions" in js


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
