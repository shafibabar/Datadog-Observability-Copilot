"""Real-browser smoke test for the product UI (opt-in).

Unlike tests/test_web_ui.py (which asserts served markup), this drives an actual
browser so it catches things only a render exposes — e.g. caret positioning for
the @ menu, or a chip actually landing in the composer. It is SKIPPED unless
Playwright and a browser are installed, so the default offline suite stays green.

To enable it (on a machine with network):
    pip install playwright
    playwright install chromium
    pytest tests/test_smoke_playwright.py

It launches the app itself (uvicorn subprocess, replay data source, no keys) and
only exercises UI that works without an LLM backend: typing "@" in the composer
to open the scope menu, drilling into its Duration submenu (static), and picking
an Environment value to confirm a locked chip lands inline.
"""
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

# Skip the whole module unless Playwright is importable.
sync_api = pytest.importorskip("playwright.sync_api")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):  # up to ~10s for the server to come up
            try:
                urllib.request.urlopen(url + "/healthz", timeout=0.5)
                break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.skip("app server did not start")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def page(base_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # browser binary not installed
            pytest.skip(f"no browser available: {exc}")
        pg = browser.new_page()
        pg.goto(base_url, wait_until="domcontentloaded")
        pg.wait_for_selector("#input")
        yield pg
        browser.close()


def _type_at(page):
    page.click("#input")
    page.keyboard.type("@")


def test_at_sign_opens_the_menu_with_categories(page):
    _type_at(page)
    menu = page.locator("#at-menu")
    menu.wait_for(state="visible")
    for category in ("Environment", "Tenant", "Duration"):
        assert menu.get_by_text(category, exact=False).first.is_visible()
    # clean up so later tests start from an empty composer
    page.keyboard.press("Escape")
    page.locator("#input").evaluate("el => el.innerHTML = ''")


def test_duration_submenu_shows_presets(page):
    _type_at(page)
    page.locator("#at-menu").get_by_text("Duration", exact=False).first.click()
    menu = page.locator("#at-menu")
    # drilling in must NOT close the menu and must list presets
    assert menu.get_by_text("Last 1 hour").first.is_visible()
    assert menu.get_by_text("Last 1 week").first.is_visible()
    page.keyboard.press("Escape")
    page.locator("#input").evaluate("el => el.innerHTML = ''")


def test_picking_an_environment_inserts_a_locked_chip(page):
    _type_at(page)
    page.locator("#at-menu").get_by_text("Environment", exact=False).first.click()
    menu = page.locator("#at-menu")
    menu.locator(".scope-opt").first.click()
    chip = page.locator("#input .scope-chip")
    assert chip.count() == 1
    assert chip.get_attribute("contenteditable") == "false"
    page.locator("#input").evaluate("el => el.innerHTML = ''")


def test_composer_and_persona_control_are_present(page):
    assert page.locator("#input").is_visible()
    assert page.locator("#send").count() == 1
    assert page.locator("#persona").is_visible()
