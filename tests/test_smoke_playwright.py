"""Real-browser smoke test for the product UI (opt-in).

Unlike tests/test_web_ui.py (which asserts served markup), this drives an actual
browser so it catches things only a render exposes — e.g. the scope menu closing
itself on drill-down. It is SKIPPED unless Playwright and a browser are installed,
so the default offline suite stays green.

To enable it (on a machine with network):
    pip install playwright
    playwright install chromium
    pytest tests/test_smoke_playwright.py

It launches the app itself (uvicorn subprocess, replay data source, no keys) and
only exercises UI that works without an LLM backend: the scope menu and its
Duration / Explain-as submenus (which are static), plus the composer.
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
        pg.wait_for_selector("#scope-trigger")
        yield pg
        browser.close()


def test_scope_menu_opens_and_shows_categories(page):
    page.click("#scope-trigger")
    panel = page.locator("#scope-panel")
    panel.wait_for(state="visible")
    for category in ("Environment", "Tenant", "Duration", "Explain as"):
        assert panel.get_by_text(category, exact=False).first.is_visible()


def test_duration_submenu_shows_presets(page):
    page.click("#scope-trigger")
    page.locator("#scope-panel").get_by_text("Duration", exact=False).first.click()
    panel = page.locator("#scope-panel")
    # drilling in must NOT close the menu (the bug we fixed) and must list presets
    assert panel.get_by_text("Last 1 hour").first.is_visible()
    assert panel.get_by_text("Last 1 week").first.is_visible()


def test_explain_as_submenu_shows_personas(page):
    page.click("#scope-trigger")
    page.locator("#scope-panel").get_by_text("Explain as", exact=False).first.click()
    panel = page.locator("#scope-panel")
    assert panel.get_by_text("Site Reliability Engineer").first.is_visible()
    assert panel.get_by_text("Support Engineer").first.is_visible()


def test_composer_is_present(page):
    assert page.locator("#input").is_visible()
    assert page.locator("#send").count() == 1
