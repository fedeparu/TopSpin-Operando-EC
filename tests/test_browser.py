"""Opt-in Chromium checks of the shared-time operando workspace.

ECNMR_BROWSER=1 pytest tests/test_browser.py -q
ECNMR_REAL_DATA adds an import check with the supplied experimental recordings.
Screenshots are private when ECNMR_SCREENSHOTS points outside the repository.
"""
from __future__ import annotations

import json
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

pytestmark = pytest.mark.skipif(os.environ.get("ECNMR_BROWSER") != "1", reason="Set ECNMR_BROWSER=1 for Chromium acceptance tests")


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
            browser_path = os.getenv("ECNMR_CHROMIUM") or shutil.which("chromium") or shutil.which("google-chrome")
            launch = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
            if browser_path:
                launch["executable_path"] = browser_path
            browser = playwright.chromium.launch(**launch)
            page = browser.new_page(viewport={"width": 1600, "height": 1100}, device_scale_factor=1)
            page.set_default_timeout(30000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            ready(page)
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


def ready(page):
    page.wait_for_function("window.ECNMR?.ready && window.ECNMR?.experiment && !!document.querySelector('#ec-plot')._ev?._events?.plotly_hover && document.querySelector('#heatmap-plot')._fullLayout")
    page.locator("#busy-overlay").wait_for(state="hidden")


def screenshot(page, name):
    destination = os.environ.get("ECNMR_SCREENSHOTS")
    if destination:
        folder = Path(destination)
        folder.mkdir(parents=True, exist_ok=True)
        page.mouse.move(10, 10)
        page.screenshot(path=str(folder / name), full_page=True)


def plot_point(page, plot_id, x, y):
    page.locator("#busy-overlay").wait_for(state="hidden")
    page.locator(f"#{plot_id}").scroll_into_view_if_needed()
    return page.evaluate("""({id,x,y}) => {
      const p=document.getElementById(id), b=p.getBoundingClientRect(), l=p._fullLayout;
      return {x:b.left+l.xaxis._offset+l.xaxis.d2p(x),
              y:b.top+l.yaxis._offset+l.yaxis.d2p(y)};
    }""", {"id": plot_id, "x": x, "y": y})


def mouse_point(page, plot_id, x, y, click=False):
    position = plot_point(page, plot_id, x, y)
    page.mouse.move(position["x"], position["y"])
    if click:
        page.mouse.click(position["x"], position["y"])


def ec_point(page, time_s):
    """Choose a retained rendered sample; long real traces are thinned."""
    return page.evaluate("""t => {
      const trace=document.querySelector('#ec-plot').data.find(s=>s.x?.length && s.y?.length);
      let i=0;
      for(let j=1;j<trace.y.length;j++)
        if(Math.abs(trace.y[j]*3600-t)<Math.abs(trace.y[i]*3600-t)) i=j;
      return {voltage_V:trace.x[i],time_h:trace.y[i]};
    }""", time_s)


def hover_ec(page, time_s, click=False):
    point = ec_point(page, time_s)
    mouse_point(page, "ec-plot", point["voltage_V"], point["time_h"], click=click)
    return point


def hover_stack(page, spectrum_id, click=False):
    point = page.evaluate("""id => {
      const p=document.querySelector('#heatmap-plot');
      const trace=p.data.find(s=>s.meta?.spectrum_id===id || s.customdata?.includes(id));
      if(!trace) throw new Error('No rendered stacked trace for '+id);
      const indices=Array.from({length:trace.x.length},(_,i)=>i).filter(i=>Number.isFinite(trace.x[i]) && Number.isFinite(trace.y[i]) && (trace.meta?.spectrum_id===id || trace.customdata?.[i]===id));
      const i=indices.reduce((a,b)=>Math.abs(trace.x[b]-5)<Math.abs(trace.x[a]-5)?b:a);
      return {x:trace.x[i],y:trace.y[i]};
    }""", spectrum_id)
    mouse_point(page, "heatmap-plot", point["x"], point["y"], click=click)


def wait_current(page, spectrum_id):
    page.wait_for_function("id=>window.ECNMR.currentId===id", arg=spectrum_id)


def time_ranges(page):
    return page.evaluate("[document.querySelector('#ec-plot')._fullLayout.yaxis.range,document.querySelector('#heatmap-plot')._fullLayout.yaxis.range]")


def test_hover_lock_shared_zoom_and_saved_view_settings(workspace, tmp_path):
    page, _ = workspace
    assert page.evaluate("window.ECNMR.experiment.ec.time_s.length") == 721
    assert page.evaluate("window.ECNMR.experiment.spectra.length") == 24
    assert page.locator("#series-view").input_value() == "stacked"
    assert not page.locator("#peak-analysis").evaluate("el=>el.open")
    assert page.locator("#peak-plot").is_hidden()
    assert time_ranges(page)[0] == pytest.approx(time_ranges(page)[1])

    # A real mouse hover, without clicking, links the vertical EC curve to NMR.
    hover_ec(page, 1000)
    wait_current(page, "synthetic-04")
    page.wait_for_function("document.querySelector('#heatmap-plot').data.some(t=>t.meta?.spectrum_id==='synthetic-04')")
    page.wait_for_function("document.querySelector('#ec-plot').layout.shapes?.some(s=>s.type==='rect' && Math.abs(s.y0-900/3600)<1e-6)")
    assert not page.evaluate("window.ECNMR.locked")
    page.wait_for_function("document.querySelector('#spectrum-plot').data.length===1")
    assert page.evaluate("Math.max(...document.querySelector('#spectrum-plot').data[0].y)") == pytest.approx(page.evaluate("Math.max(...window.ECNMR.experiment.spectra[3].intensity)"))
    assert page.evaluate("document.querySelector('#spectrum-plot')._fullLayout.xaxis.range[0] > document.querySelector('#spectrum-plot')._fullLayout.xaxis.range[1]")

    # Hover an actual displaced stacked spectrum, then pin it by clicking.
    hover_stack(page, "synthetic-08")
    wait_current(page, "synthetic-08")
    page.wait_for_function("document.querySelector('#ec-plot').layout.shapes?.some(s=>s.type==='rect' && Math.abs(s.y0-2100/3600)<1e-6)")
    hover_stack(page, "synthetic-08", click=True)
    page.wait_for_function("window.ECNMR.locked && window.ECNMR.selectedId==='synthetic-08'")
    hover_ec(page, 1000)
    assert page.evaluate("window.ECNMR.currentId") == "synthetic-08"
    page.locator("#unlock-button").click()
    hover_ec(page, 1900)
    wait_current(page, "synthetic-07")

    # Contour and stacked modes use the same increasing-down experiment clock.
    page.locator("#series-view").select_option("contour")
    page.wait_for_function("document.querySelector('#heatmap-plot').data.some(t=>t.type==='contour')")
    mouse_point(page, "heatmap-plot", 5, 3420 / 3600)
    wait_current(page, "synthetic-12")
    mouse_point(page, "heatmap-plot", 5, 3420 / 3600, click=True)
    page.wait_for_function("window.ECNMR.locked")

    # A user drag zoom on the EC plot must also update the spectral timeline.
    start = plot_point(page, "ec-plot", 3.4, 0.25)
    finish = plot_point(page, "ec-plot", 4.0, 1.3)
    page.mouse.move(start["x"], start["y"])
    page.mouse.down()
    page.mouse.move(finish["x"], finish["y"], steps=12)
    page.mouse.up()
    page.wait_for_function("Math.abs(document.querySelector('#ec-plot')._fullLayout.yaxis.range[0]-document.querySelector('#heatmap-plot')._fullLayout.yaxis.range[0])<1e-6 && Math.abs(document.querySelector('#ec-plot')._fullLayout.yaxis.range[1]-document.querySelector('#heatmap-plot')._fullLayout.yaxis.range[1])<1e-6")
    ranges = time_ranges(page)
    assert abs(ranges[0][1] - ranges[0][0]) < 1.5

    gain = float(page.locator("#gain-input").input_value())
    page.locator("#gain-input").focus()
    page.locator("#gain-input").press("ArrowRight")
    assert float(page.locator("#gain-input").input_value()) > gain
    with page.expect_download() as download:
        page.get_by_test_id("save-button").click()
    session = tmp_path / "view.json"
    download.value.save_as(str(session))
    saved = json.loads(session.read_text())
    assert saved["analysis"]["series_view"] == "contour"
    assert saved["analysis"]["locked"] is True
    assert saved["analysis"]["selected_id"] == "synthetic-12"
    assert saved["analysis"]["time_range"] == pytest.approx(ranges[0])
    saved_gain = float(page.locator("#gain-input").input_value())
    assert saved["analysis"]["gain"] == pytest.approx(saved_gain)
    page.locator("#series-view").select_option("stacked")
    page.locator("#unlock-button").click()
    page.get_by_test_id("session-file").set_input_files(str(session))
    page.wait_for_function("document.querySelector('#series-view').value==='contour' && window.ECNMR.locked")
    assert time_ranges(page)[0] == pytest.approx(ranges[0])
    assert float(page.locator("#gain-input").input_value()) == pytest.approx(saved_gain)
    screenshot(page, "workspace-synthetic-ux.png")


def test_progressive_simulation_preserves_locked_spectrum_and_shared_time_zoom(workspace):
    page, _ = workspace
    page.get_by_test_id("mode-simulation").click()
    page.get_by_test_id("speed-select").select_option("60")
    page.get_by_test_id("prepare-button").click()
    page.get_by_test_id("start-button").click()
    page.wait_for_function("window.ECNMR.state.state==='running' && window.ECNMR.state.available_ec>2")
    assert page.evaluate("window.ECNMR.state.available_spectra") == 0
    page.wait_for_function("window.ECNMR.state.available_spectra>=1", timeout=15000)
    page.locator("#spectrum-select").select_option("synthetic-01")
    page.wait_for_function("window.ECNMR.locked")
    page.evaluate("Plotly.relayout('ec-plot', {'yaxis.range':[0.4,0], 'yaxis.autorange':false})")
    page.wait_for_function("Math.abs(document.querySelector('#heatmap-plot')._fullLayout.yaxis.range[0]-.4)<1e-6")
    count = page.evaluate("window.ECNMR.state.available_spectra")
    page.wait_for_function("n=>window.ECNMR.state.available_spectra>n", arg=count)
    assert page.evaluate("window.ECNMR.currentId") == "synthetic-01"
    assert time_ranges(page)[0] == pytest.approx([0.4, 0])
    assert time_ranges(page)[1] == pytest.approx([0.4, 0])

    page.locator(".failure-details summary").click()
    page.get_by_test_id("disconnect-button").click()
    page.wait_for_function("window.ECNMR.state.state==='paused'")
    counts = page.evaluate("[window.ECNMR.state.available_ec,window.ECNMR.state.available_spectra]")
    page.wait_for_timeout(1000)
    assert page.evaluate("[window.ECNMR.state.available_ec,window.ECNMR.state.available_spectra]") == counts
    page.get_by_test_id("reconnect-button").click()
    page.wait_for_function("n=>window.ECNMR.state.available_ec>n", arg=counts[0])
    screenshot(page, "workspace-simulation-ux.png")
    page.get_by_test_id("stop-button").click()
    page.wait_for_function("window.ECNMR.state.state==='stopped'")


@pytest.mark.real
def test_real_import_defaults_to_labelled_same_start_estimate_with_unknown_uncertainty(workspace, tmp_path):
    root = os.getenv("ECNMR_REAL_DATA")
    if not root:
        pytest.skip("Set ECNMR_REAL_DATA to the extracted experimental files")
    root = Path(root)
    mpr = next(root.rglob("*.mpr"))
    experiment = next(p.parent for p in root.rglob("acqus") if (p.parent / "pdata" / "1" / "2rr").exists())
    nmr_zip = tmp_path / "nmr.zip"
    with zipfile.ZipFile(nmr_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in experiment.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(experiment.parent))
    page, _ = workspace
    page.get_by_test_id("import-button").click()
    page.get_by_test_id("ec-file").set_input_files(str(mpr))
    page.get_by_test_id("nmr-file").set_input_files(str(nmr_zip))
    page.get_by_test_id("import-submit").click()
    page.wait_for_function("window.ECNMR.experiment.spectra.length===64", timeout=60000)
    ready(page)
    experiment = page.evaluate("window.ECNMR.experiment")
    assert len(experiment["ec"]["time_s"]) == 98790
    alignment = experiment["alignment"]
    assert alignment["method"] == "manual"
    assert alignment["assumption"] == "same_start"
    assert alignment["offset_s"] == 0
    assert alignment["uncertainty_s"] is None
    cadence = 74397 / 64
    assert alignment["assumed_interval_s"] == pytest.approx(cadence)
    assert experiment["spectra"][0]["time_s"] == 0
    assert experiment["spectra"][-1]["time_s"] == pytest.approx(cadence * 63)
    assert "estimat" in page.locator("#timing-chip").inner_text().lower()
    assert page.locator("#series-view").input_value() == "stacked"
    assert not page.locator("#peak-analysis").evaluate("el=>el.open")
    assert time_ranges(page)[0] == pytest.approx(time_ranges(page)[1])
    assert max(time_ranges(page)[0]) < 22  # NMR coverage, not stretched to the 52 h EC run.
    hover_ec(page, cadence * 20.25)
    wait_current(page, experiment["spectra"][20]["id"])
    page.wait_for_function("id=>document.querySelector('#spectrum-plot').data[0].meta?.spectrum_id===id && document.querySelector('#spectrum-plot').data[0].y.length===4096", arg=experiment["spectra"][20]["id"])
    detail = page.evaluate("({ppm:document.querySelector('#spectrum-plot').data[0].x,intensity:document.querySelector('#spectrum-plot').data[0].y})")
    assert detail["ppm"] == experiment["spectra"][20]["ppm"]
    assert detail["intensity"] == experiment["spectra"][20]["intensity"]
    page.locator("#settings-button").click()
    page.locator("#alignment-details summary").click()
    assert page.locator("#uncertainty-input").input_value() == ""
    page.locator("#settings-dialog .dialog-close").first.click()
    page.locator("#spectrum-select").select_option(experiment["spectra"][20]["id"])
    page.wait_for_function("window.ECNMR.locked")
    screenshot(page, "workspace-real-same-start.png")
    page.locator("#series-view").select_option("contour")
    page.wait_for_function("document.querySelector('#heatmap-plot').data.some(t=>t.type==='contour')")
    screenshot(page, "workspace-real-contour.png")
    page.locator("#time-window").select_option("full")
    page.wait_for_function("Math.max(...document.querySelector('#ec-plot')._fullLayout.yaxis.range)>51")
    assert time_ranges(page)[0] == pytest.approx(time_ranges(page)[1])
    pinned = page.evaluate("window.ECNMR.selectedId")
    page.locator("#unlock-button").click()
    hover_ec(page, 40 * 3600)
    page.wait_for_function("window.ECNMR.currentId===null")
    assert page.evaluate("window.ECNMR.hoveredId") is None
    assert page.evaluate("window.ECNMR.selectedId") == pinned
    assert "No NMR" in page.locator("#match-description").inner_text()
    assert not page.evaluate("document.querySelector('#ec-plot').layout.shapes.length")
