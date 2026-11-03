"""Run the exported HTML itself, with no service or external plotting assets.

The managed Chromium policy blocks file:// navigation. set_content exercises
the exact saved bytes in a fresh browser document without changing that policy.
"""
import json
import os
from pathlib import Path
import shutil

import pytest

from ecnmr.standalone import build_html
from ecnmr.synthetic import demo

pytestmark = pytest.mark.skipif(os.environ.get("ECNMR_BROWSER") != "1", reason="Set ECNMR_BROWSER=1 for real Chromium checks")


@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        executable = os.getenv("ECNMR_CHROMIUM") or shutil.which("chromium")
        args = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if executable:
            args["executable_path"] = executable
        instance = p.chromium.launch(**args)
        yield instance
        instance.close()


def open_html(browser, path):
    page = browser.new_page(viewport={"width": 1600, "height": 1100})
    page.set_default_timeout(30000)
    errors, requests = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: requests.append(r.url) if r.url.startswith(("http:", "https:")) else None)
    page.set_content(path.read_text(encoding="utf-8"), wait_until="load")
    page.wait_for_function("window.ECNMR?.experiment && !!document.querySelector('#ec-plot')._ev?._events?.plotly_click")
    return page, errors, requests


def test_downloaded_html_linking_exports_simulation_and_reopen_without_a_server(browser, tmp_path):
    html = tmp_path / "standalone.html"
    html.write_text(build_html(), encoding="utf-8")
    page, errors, requests = open_html(browser, html)
    coords = page.evaluate("""() => {
      const plot = document.querySelector('#ec-plot'), l = plot._fullLayout, b = plot.getBoundingClientRect();
      const t=1000, v=3.25+0.85*Math.sin(Math.PI*t/7200);
      return {x:b.left+l.xaxis._offset+l.xaxis.d2p(t/3600),y:b.top+l.yaxis._offset+l.yaxis.d2p(v)};
    }""")
    page.mouse.click(coords["x"], coords["y"])
    page.wait_for_function("window.ECNMR.selectedIds.has('synthetic-04')")
    page.locator('[data-spectrum-id="synthetic-06"] input').check()
    page.wait_for_function("window.ECNMR.selectedIds.size===2")
    with page.expect_download() as download:
        page.get_by_test_id("save-button").click()
    session = tmp_path / "session.json"
    download.value.save_as(str(session))
    saved = json.loads(session.read_text())
    assert sorted(saved["analysis"]["selected_ids"]) == ["synthetic-04", "synthetic-06"]
    with page.expect_download() as download:
        page.get_by_test_id("download-html").click()
    downloaded = tmp_path / "downloaded.html"
    download.value.save_as(str(downloaded))
    assert downloaded.stat().st_size > 3_000_000
    reopened, reopened_errors, reopened_requests = open_html(browser, downloaded)
    reopened.get_by_test_id("session-file").set_input_files(str(session))
    reopened.wait_for_function("window.ECNMR.selectedIds.has('synthetic-04') && window.ECNMR.selectedIds.has('synthetic-06')")
    reopened.get_by_test_id("mode-simulation").click()
    reopened.get_by_test_id("prepare-button").click()
    reopened.get_by_test_id("start-button").click()
    reopened.wait_for_function("window.ECNMR.state.state==='running' && window.ECNMR.state.available_ec>2")
    reopened.wait_for_function("window.ECNMR.state.available_spectra>=1")
    reopened.locator(".failure-details summary").click()
    reopened.get_by_test_id("disconnect-button").click()
    reopened.wait_for_function("window.ECNMR.state.state==='paused'")
    count = reopened.evaluate("window.ECNMR.state.available_ec")
    reopened.wait_for_timeout(1100)
    assert reopened.evaluate("window.ECNMR.state.available_ec") == count
    reopened.get_by_test_id("reconnect-button").click()
    reopened.wait_for_function("n=>window.ECNMR.state.available_ec>n", arg=count)
    reopened.get_by_test_id("stop-button").click()
    reopened.wait_for_function("window.ECNMR.state.state==='stopped'")
    assert errors == reopened_errors == []
    assert requests == reopened_requests == []


@pytest.mark.real
def test_real_file_html_unknown_timing_and_safe_synthetic_playback(browser, tmp_path):
    root = os.environ.get("ECNMR_REAL_DATA")
    if not root:
        pytest.skip("Set ECNMR_REAL_DATA for original-data HTML test")
    from ecnmr.server import load_paths
    root = Path(root)
    html = tmp_path / "real.html"
    html.write_text(build_html(load_paths(next(root.rglob("*.mpr")), root / "4")), encoding="utf-8")
    page, errors, requests = open_html(browser, html)
    assert page.evaluate("window.ECNMR.experiment.ec.time_s.length") == 98790
    assert page.evaluate("window.ECNMR.experiment.spectra.length") == 64
    assert page.evaluate("window.ECNMR.experiment.spectra.every(s=>s.time_s===null)")
    assert page.locator("#uncertainty-input").input_value() == ""
    assert page.locator("#peak-axis").input_value() == "index"
    assert page.locator("#peak-count").inner_text().startswith("64 / 64")
    page.get_by_test_id("mode-simulation").click()
    page.wait_for_function("window.ECNMR.experiment.metadata.synthetic===true")
    assert "SYNTHETIC" in page.locator("#data-badge").inner_text().upper()
    page.get_by_test_id("real-button").click()
    page.wait_for_function("window.ECNMR.experiment.spectra.length===64")
    page.locator("#alignment-details summary").click()
    page.get_by_test_id("interval-input").fill("1200")
    page.locator("#duration-input").fill("900")
    page.get_by_test_id("apply-alignment").click()
    page.wait_for_function("window.ECNMR.experiment.alignment.method==='manual'")
    assert page.evaluate("window.ECNMR.experiment.alignment.uncertainty_s") is None
    assert page.evaluate("window.ECNMR.experiment.spectra[25].time_s") == 30000
    shots = os.environ.get("ECNMR_SCREENSHOTS")
    if shots:
        target = Path(shots)
        target.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target / "standalone-real.png"), full_page=True)
    assert not errors
    assert not requests
