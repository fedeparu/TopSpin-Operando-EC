"""Opt-in real Chromium acceptance tests against the actual local application.

Run: ECNMR_BROWSER=1 pytest tests/test_browser.py -q
Set ECNMR_CHROMIUM to a browser executable or install Playwright Chromium.
ECNMR_REAL_DATA adds a real-data import/unaligned/alignment/linking check.
ECNMR_SCREENSHOTS writes review images outside the source repository.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ECNMR_BROWSER") != "1", reason="Set ECNMR_BROWSER=1 to run Chromium acceptance tests")


@pytest.fixture
def workspace(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    output = (tmp_path / "server.log").open("w+")
    process = subprocess.Popen([sys.executable, "-m", "ecnmr", "--port", str(port), "--state-dir", str(tmp_path / "state")],
                               cwd=Path(__file__).parents[1], stdout=output, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            if process.poll() is not None:
                output.seek(0)
                pytest.fail("Server exited: " + output.read())
            try:
                with urllib.request.urlopen(url + "/api/state", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("Local application did not start")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser_path = os.environ.get("ECNMR_CHROMIUM") or shutil.which("chromium") or shutil.which("google-chrome")
            launch = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
            if browser_path:
                launch["executable_path"] = browser_path
            browser = playwright.chromium.launch(**launch)
            page = browser.new_page(viewport={"width": 1600, "height": 1100}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.set_default_timeout(30000)
            page.goto(url)
            page.wait_for_function("window.ECNMR && window.ECNMR.experiment && document.querySelector('#ec-plot')._fullLayout && !!document.querySelector('#ec-plot')._ev?._events?.plotly_click")
            yield page, url
            assert not errors, "Browser JavaScript errors: " + "; ".join(errors)
            browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        output.close()


def selected(page):
    return page.evaluate("Array.from(window.ECNMR.selectedIds)")


def chart_click(page, time_s, voltage):
    """Click a real rendered potential trace; exercise Plotly's browser hit test."""
    page.locator("#busy-overlay").wait_for(state="hidden")
    page.get_by_test_id("ec-plot").scroll_into_view_if_needed()
    coords = page.evaluate("""({t,v}) => {
      const plot=document.querySelector('#ec-plot');
      const box=plot.getBoundingClientRect();
      const layout=plot._fullLayout;
      return {x:box.left+layout.xaxis._offset+layout.xaxis.d2p(t/3600),
              y:box.top+layout.yaxis._offset+layout.yaxis.d2p(v)};
    }""", {"t": time_s, "v": voltage})
    page.mouse.move(coords["x"], coords["y"])
    page.mouse.click(coords["x"], coords["y"])


def screenshot(page, name):
    destination = os.environ.get("ECNMR_SCREENSHOTS")
    if destination:
        folder = Path(destination)
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / name), full_page=True)


def test_offline_linking_overlay_save_reopen_and_progressive_simulation(workspace, tmp_path):
    page, url = workspace
    assert page.get_by_test_id("metric-ec").inner_text().replace(",", "") == "721"
    assert page.get_by_test_id("metric-spectra").inner_text() == "24"
    assert "SYNTHETIC" in page.locator("#data-badge").inner_text().upper()

    # Select an EC point inside acquisition 4; no injected Plotly event.
    chart_click(page, 1000, 3.25 + 0.85 * math.sin(math.pi * 1000 / 7200))
    page.wait_for_function("Array.from(window.ECNMR.selectedIds).includes('synthetic-04')")
    assert "synthetic-04" in selected(page)

    # Selecting a spectrum from the actual list highlights its acquisition.
    row = page.locator('[data-spectrum-id="synthetic-08"]')
    row.click()
    page.wait_for_function("Array.from(window.ECNMR.selectedIds).includes('synthetic-08')")
    page.wait_for_function("document.querySelector('#ec-plot').layout.shapes.some(s => s.type === 'rect' && Math.abs(s.x0 - 2100/3600) < 0.000001)")
    shape = page.evaluate("document.querySelector('#ec-plot').layout.shapes.find(s => s.type === 'rect')")
    assert shape is not None
    assert shape["x0"] == pytest.approx(2100 / 3600)
    assert shape["x1"] == pytest.approx(2340 / 3600)

    # A second acquisition can be overlaid with the first, then saved and restored.
    page.locator('[data-spectrum-id="synthetic-10"] input[type="checkbox"]').check()
    page.wait_for_function("Array.from(window.ECNMR.selectedIds).length === 2")
    assert len(page.locator("#spectrum-plot").evaluate("el=>el.data")) == 2
    before = sorted(selected(page))
    with page.expect_download() as download:
        page.get_by_test_id("save-button").click()
    session = tmp_path / "saved-analysis.json"
    download.value.save_as(str(session))
    saved = json.loads(session.read_text())
    assert sorted(saved["analysis"]["selected_ids"]) == before

    page.get_by_test_id("clear-overlays").click()
    page.get_by_test_id("session-file").set_input_files(str(session))
    page.wait_for_function("ids => JSON.stringify(Array.from(window.ECNMR.selectedIds).sort()) === JSON.stringify(ids)", arg=before)
    assert sorted(selected(page)) == before

    # Simulated measurements and spectra become visible progressively.
    page.get_by_test_id("mode-simulation").click()
    page.get_by_test_id("speed-select").select_option("60")
    page.get_by_test_id("prepare-button").click()
    page.get_by_test_id("start-button").click()
    page.wait_for_function("window.ECNMR.state.state === 'running' && window.ECNMR.state.available_ec > 2")
    first = page.evaluate("window.ECNMR.state.available_ec")
    assert page.evaluate("window.ECNMR.state.available_spectra") == 0
    page.wait_for_function("n => window.ECNMR.state.available_ec > n", arg=first)
    page.wait_for_function("window.ECNMR.state.available_spectra >= 1", timeout=15000)
    screenshot(page, "simulation.png")

    # Failure injection freezes both streams and leaves the acquired data intact.
    page.locator(".failure-details summary").click()
    page.get_by_test_id("disconnect-button").click()
    page.wait_for_function("window.ECNMR.state.state === 'paused'")
    counts = page.evaluate("[window.ECNMR.state.available_ec,window.ECNMR.state.available_spectra]")
    page.wait_for_timeout(1200)
    assert page.evaluate("[window.ECNMR.state.available_ec,window.ECNMR.state.available_spectra]") == counts
    page.get_by_test_id("reconnect-button").click()
    page.wait_for_function("window.ECNMR.state.state === 'running'")
    page.wait_for_function("n => window.ECNMR.state.available_ec > n", arg=counts[0])

    # Turning off follow-latest preserves an explicit selection while updates arrive.
    page.locator("#follow-latest").uncheck()
    page.get_by_test_id('spectrum-row').first.click()
    selection = selected(page)
    # Preserve user zoom and overlays while another completed acquisition arrives.
    page.wait_for_function("window.ECNMR.state.available_spectra >= 2")
    page.get_by_test_id("spectrum-row").nth(1).locator('input[type="checkbox"]').check()
    page.wait_for_function("Array.from(window.ECNMR.selectedIds).length === 2")
    selection = selected(page)
    page.evaluate("Plotly.relayout('ec-plot', {'xaxis.range':[0,0.4], 'xaxis.autorange':false})")
    count = page.evaluate("window.ECNMR.state.available_spectra")
    page.wait_for_function("n => window.ECNMR.state.available_spectra > n", arg=count)
    assert selected(page) == selection
    assert page.evaluate("document.querySelector('#ec-plot')._fullLayout.xaxis.range") == pytest.approx([0,0.4])
    page.get_by_test_id("stop-button").click()
    page.wait_for_function("window.ECNMR.state.state === 'stopped'")


@pytest.mark.real
def test_real_import_requires_explicit_alignment_and_links_after_operator_assumption(workspace, tmp_path):
    root = os.environ.get("ECNMR_REAL_DATA")
    if not root:
        pytest.skip("Set ECNMR_REAL_DATA to the extracted uploaded datasets")
    root = Path(root)
    mpr = next(root.rglob("*.mpr"))
    experiment = next(p.parent for p in root.rglob("acqus") if (p.parent / "pdata" / "1" / "2rr").exists())
    nmr_zip = tmp_path / "nmr.zip"
    with zipfile.ZipFile(nmr_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in experiment.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(experiment.parent))
    page, url = workspace
    page.get_by_test_id("import-button").click()
    page.get_by_test_id("ec-file").set_input_files(str(mpr))
    page.get_by_test_id("nmr-file").set_input_files(str(nmr_zip))
    page.get_by_test_id("import-submit").click()
    page.wait_for_function("window.ECNMR.experiment.spectra.length === 64", timeout=60000)
    assert page.get_by_test_id("metric-ec").inner_text().replace(",", "") == "98790"
    assert page.evaluate("window.ECNMR.experiment.alignment.method") == "unaligned"
    assert page.evaluate("window.ECNMR.experiment.spectra.every(s => s.time_s === null)")
    assert page.locator("#notice-banner").is_visible()
    page.locator("#busy-overlay").wait_for(state="hidden")
    assert page.locator("#uncertainty-input").input_value() == ""
    screenshot(page, "offline-real-data-unaligned.png")

    # Explicitly assumed test cadence exercises linking, without asserting true sync.
    page.locator("#alignment-details summary").click()
    page.get_by_test_id("offset-input").fill("0")
    page.get_by_test_id("interval-input").fill("1200")
    page.locator("#duration-input").fill("900")
    page.get_by_test_id("apply-alignment").click()
    page.wait_for_function("window.ECNMR.experiment.alignment.method === 'manual'")
    assert page.evaluate("window.ECNMR.experiment.alignment.uncertainty_s") is None
    e = page.evaluate("window.ECNMR.experiment")
    # Long real curves are thinned for display. Click a retained rendered point,
    # rather than assuming every original sample is independently hit-testable.
    point = page.evaluate("""() => {
      const trace=document.querySelector('#ec-plot').data[0];
      let index=0;
      for (let i=1;i<trace.x.length;i++)
        if(Math.abs(trace.x[i]*3600-30500)<Math.abs(trace.x[index]*3600-30500)) index=i;
      return {time_s:trace.x[index]*3600,voltage_V:trace.y[index]};
    }""")
    chart_click(page, point["time_s"], point["voltage_V"])
    expected_index = int(point["time_s"] // 1200)
    expected = e["spectra"][expected_index]["id"]
    page.wait_for_function("id => Array.from(window.ECNMR.selectedIds).includes(id)", arg=expected)
    assert expected in selected(page)
    screenshot(page, "offline-real-data.png")
