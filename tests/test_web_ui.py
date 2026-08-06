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


def test_at_menu_hides_a_dimension_with_no_options():
    # A minimal live config (tenants only, no COPILOT_PLATFORM_ENVIRONMENTS) must
    # not offer an "Environment" row that dead-ends on "No matches".
    js = _js()
    root = js[js.index("function renderAtMenu"):js.index("function positionAtMenu")]
    assert "envOptions.length" in root and "tenantOptions.length" in root
    # Duration is always available — it needs no discovered options.
    assert "Duration" in root


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


# --- Phase B: quantitative reply rendering ---------------------------------

def _css() -> str:
    return client.get("/static/styles.css").text


def test_markdown_renderer_turns_a_confidence_token_into_a_chip():
    """The reply is persisted and copied as PLAIN TEXT, so confidence travels as
    a "[high]" token. The chip is produced at render time, which means reloaded
    history gets chips too — not just the live turn."""
    js = _js()
    assert "conf-" in js
    # the bracket token is recognised and rewritten
    assert "[high]" in js or "low|medium|high" in js


def test_confidence_chip_styles_cover_all_three_levels():
    css = _css()
    for level in ("conf-low", "conf-medium", "conf-high"):
        assert f".{level}" in css


def test_metric_lines_are_rendered_with_tabular_figures():
    """Metric values sit under one another in the reply; proportional digits
    make columns of numbers impossible to compare at a glance."""
    css = _css()
    assert "tabular-nums" in css


def test_workspace_panel_renders_the_new_section_kinds():
    js = _js()
    assert '"gaps"' in js
    assert '"mapping"' in js


# --- reply-rendering logic, bound to real render() output -------------------
#
# There is no JS engine in this environment, so app.js is not EXECUTED here.
# Instead each line-classifying pattern is asserted to exist verbatim in the
# served asset and is then run — compiled in Python, the syntax is identical for
# these — against the actual output of app.personas.render(). That catches the
# failure that matters: the renderer and the reply format drifting apart. It
# does not catch a JS syntax error, which only a browser run would.

import re as _re

_LIST_ITEM = r"/^[-*]\s+(.*)$/"
_CONTINUATION = r"/^\s{2,}(\S.*)$/"
_SECTION_LABEL = r"/^[A-Z][^.!?]{0,40}:$/"
_CONFIDENCE = r"/\s*\[(low|medium|high)\]/g"


def _pattern(js_literal: str) -> _re.Pattern:
    """Compile a JS regex literal's body with Python's engine."""
    body = js_literal[1:js_literal.rindex("/")]
    return _re.compile(body)


def test_every_reply_pattern_is_present_verbatim_in_the_asset():
    """If a pattern is edited in app.js, this fails and forces the behavioural
    assertions below to be re-checked rather than silently going stale."""
    js = _js()
    for literal in (_LIST_ITEM, _CONTINUATION, _SECTION_LABEL, _CONFIDENCE):
        assert literal in js, f"{literal} no longer appears in app.js"


def _rendered_reply() -> str:
    from app.personas import get_persona, render
    from tests.test_personas import make_quantified_investigation

    return render(get_persona("sre"), make_quantified_investigation())


def test_measurement_lines_are_classified_as_list_continuations():
    """The metric line under a claim must NOT be read as a new list item or a
    paragraph — either would orphan the numbers from the claim they support."""
    list_item, continuation = _pattern(_LIST_ITEM), _pattern(_CONTINUATION)
    measurements = [
        line for line in _rendered_reply().splitlines()
        if "ec.indexer.ingested_communication_event_latency" in line
        and not line.lstrip().startswith("- ")
    ]

    assert measurements, "the reply no longer emits an indented measurement line"
    for line in measurements:
        assert continuation.match(line)
        assert not list_item.match(line)


def test_section_headings_are_classified_as_labels_not_paragraphs():
    label = _pattern(_SECTION_LABEL)
    reply = _rendered_reply()

    assert label.match("Current health:")
    assert label.match("Not available:")
    assert label.match("Metrics queried:")
    assert "Current health:" in reply
    # A real sentence must not be mistaken for a label.
    assert not label.match("Checkout latency rose after the deploy.")


def test_the_confidence_token_in_a_real_reply_is_matched_by_the_chip_pattern():
    chip = _pattern(_CONFIDENCE)
    reply = _rendered_reply()

    assert "[high]" in reply
    assert chip.search(reply)
    assert {m.group(1) for m in chip.finditer(reply)} <= {"low", "medium", "high"}


def test_copying_a_reply_yields_readable_plain_text():
    """Copy-to-clipboard ships the raw string, so the token has to be legible on
    its own — the chip is a rendering nicety, not the source of truth."""
    reply = _rendered_reply()
    assert "  [high]" in reply
    assert "<span" not in reply
