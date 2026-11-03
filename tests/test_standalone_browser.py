"""Run the saved HTML itself, with no service or external plotting assets.

set_content loads the exact saved bytes; managed Chromium blocks file://.
"""
import json
import os
from pathlib import Path
import shutil

import pytest

from ecnmr.standalone import build_html

pytestmark = pytest.mark.skipif(os.environ.get("ECNMR_BROWSER") != "1", reason="Set ECNMR_BROWSER=1 for Chromium acceptance")


@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        executable = os.getenv("ECNMR_CHROMIUM") or shutil.which("chromium")
        options = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if executable:
            options["executable_path"] = executable
        instance = playwright.chromium.launch(**options)
        yield instance
        instance.close()


def open_html(browser, path):
    page = browser.new_page(viewport={"width": 1600, "height": 1100})
    page.set_default_timeout(30000)
    errors, requests = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: requests.append(request.url) if request.url.startswith(("http:", "https:")) else None)
    page.set_content(path.read_text(encoding="utf-8"), wait_until="load")
    page.wait_for_function("window.ECNMR?.ready===true")
    return page, errors, requests


def point_pixels(page, plot_id, x, y):
    page.locator("#busy-overlay").wait_for(state="hidden")
    page.locator("#" + plot_id).scroll_into_view_if_needed()
    return page.evaluate("""({id,x,y}) => {
      const p=document.getElementById(id), l=p._fullLayout, b=p.getBoundingClientRect();
      return {x:b.left+l.xaxis._offset+l.xaxis.d2p(x),y:b.top+l.yaxis._offset+l.yaxis.d2p(y)};
    }""", {"id": plot_id, "x": x, "y": y})


def hover_ec(page, target_s, *, click=False):
    # Use a retained displayed sample because long recordings are thinned.
    point = page.evaluate("""target=>{
      const t=document.querySelector('#ec-plot').data[0];let k=0;
      for(let i=1;i<t.y.length;i++) if(Math.abs(t.y[i]*3600-target)<Math.abs(t.y[k]*3600-target)) k=i;
      return {x:t.x[k],y:t.y[k]};
    }""", target_s)
    pixels = point_pixels(page, "ec-plot", point["x"], point["y"])
    page.mouse.move(pixels["x"], pixels["y"])
    if click:
        page.mouse.click(pixels["x"], pixels["y"])
    return point["y"] * 3600


def wait_highlight(page, spectrum_id):
    page.wait_for_function("""id=>{
      const s=window.ECNMR.experiment.spectra.find(s=>s.id===id);
      const detail=document.querySelector('#spectrum-plot').data;
      const series=document.querySelector('#heatmap-plot').data;
      const shapes=document.querySelector('#ec-plot').layout.shapes;
      return window.ECNMR.currentId===id && detail.some(t=>t.meta?.spectrum_id===id)
        && series.some(t=>t.meta?.spectrum_id===id)
        && shapes.some(p=>p.type==='rect' && Math.abs(p.y0-(s.time_s+window.ECNMR.experiment.alignment.offset_s)/3600)<1e-7);
    }""", arg=spectrum_id)


def screenshot(page, name):
    if destination := os.environ.get("ECNMR_SCREENSHOTS"):
        folder = Path(destination)
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / name), full_page=True)


def test_standalone_hover_lock_contour_shared_zoom_save_reopen_and_simulation(browser, tmp_path):
    html = tmp_path / "standalone.html"
    html.write_text(build_html(), encoding="utf-8")
    page, errors, requests = open_html(browser, html)
    assert page.locator("#series-view").input_value() == "stacked"
    assert not page.locator("#peak-analysis").evaluate("node=>node.open")
    assert not page.locator("#settings-dialog").evaluate("node=>node.open")

    hover_ec(page, 1000)
    wait_highlight(page, "synthetic-04")
    assert not page.evaluate("window.ECNMR.locked")
    hover_ec(page, 1000, click=True)
    page.wait_for_function("window.ECNMR.locked")
    hover_ec(page, 2200)
    page.wait_for_timeout(250)
    assert page.evaluate("window.ECNMR.currentId") == "synthetic-04"
    page.locator("#unlock-button").click()
    hover_ec(page, 2200)
    wait_highlight(page, "synthetic-08")

    # Hover a real plotted stacked-spectrum point, then the contour surface.
    stack = page.evaluate("""id=>{
      const t=document.querySelector('#heatmap-plot').data[0];let best=-1;
      for(let i=0;i<t.x.length;i++) if(t.customdata?.[i]===id && Number.isFinite(t.x[i]) && Number.isFinite(t.y[i]) &&
        (best<0 || Math.abs(t.x[i]+10)<Math.abs(t.x[best]+10))) best=i;
      if(best<0) throw Error('No displayed stacked points for '+id);
      return {x:t.x[best],y:t.y[best]};
    }""", "synthetic-12")
    pixel = point_pixels(page, "heatmap-plot", stack["x"], stack["y"])
    page.mouse.move(pixel["x"], pixel["y"])
    wait_highlight(page, "synthetic-12")
    page.locator("#series-view").select_option("contour")
    page.wait_for_function("document.querySelector('#heatmap-plot').data[0]?.type==='contour'")
    page.evaluate("Plotly.relayout('ec-plot', {'yaxis.range':[1.7,0.1], 'yaxis.autorange':false})")
    page.wait_for_function("Math.abs(document.querySelector('#heatmap-plot')._fullLayout.yaxis.range[0]-1.7)<1e-7")
    assert page.evaluate("document.querySelector('#heatmap-plot')._fullLayout.yaxis.range") == pytest.approx([1.7, 0.1])
    pixel = point_pixels(page, "heatmap-plot", 4, (4500 + 120) / 3600)
    page.mouse.move(pixel["x"], pixel["y"])
    wait_highlight(page, "synthetic-16")
    page.mouse.click(pixel["x"], pixel["y"])
    page.wait_for_function("window.ECNMR.locked && window.ECNMR.currentId==='synthetic-16'")
    with page.expect_download() as download:
        page.get_by_test_id("save-button").click()
    session = tmp_path / "session.json"
    download.value.save_as(str(session))
    assert "synthetic-16" in json.loads(session.read_text())["analysis"]["selected_ids"]
    with page.expect_download() as download:
        page.get_by_test_id("download-html").click()
    downloaded = tmp_path / "downloaded.html"
    download.value.save_as(str(downloaded))
    assert downloaded.stat().st_size > 3_000_000
    reopened, reopened_errors, reopened_requests = open_html(browser, downloaded)
    reopened.get_by_test_id("session-file").set_input_files(str(session))
    reopened.wait_for_function("window.ECNMR.currentId==='synthetic-16'")
    assert reopened.locator("#series-view").input_value() == "contour"
    assert reopened.evaluate("window.ECNMR.locked")
    assert reopened.evaluate("document.querySelector('#ec-plot')._fullLayout.yaxis.range") == pytest.approx([1.7, 0.1])
    assert reopened.evaluate("document.querySelector('#heatmap-plot')._fullLayout.yaxis.range") == pytest.approx([1.7, 0.1])

    reopened.get_by_test_id("mode-simulation").click()
    reopened.get_by_test_id("prepare-button").click()
    reopened.get_by_test_id("start-button").click()
    reopened.wait_for_function("window.ECNMR.state.state==='running' && window.ECNMR.state.available_ec>2")
    reopened.wait_for_function("window.ECNMR.state.available_spectra>=2")
    reopened.locator("#spectrum-select").select_option("synthetic-01")
    reopened.evaluate("Plotly.relayout('ec-plot', {'yaxis.range':[0.6,0], 'yaxis.autorange':false})")
    count = reopened.evaluate("window.ECNMR.state.available_spectra")
    reopened.wait_for_function("n=>window.ECNMR.state.available_spectra>n", arg=count)
    assert reopened.evaluate("window.ECNMR.currentId") == "synthetic-01"
    assert reopened.evaluate("document.querySelector('#heatmap-plot')._fullLayout.yaxis.range") == pytest.approx([0.6, 0])
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
    screenshot(reopened, "standalone-simulation-ux.png")
    assert errors == reopened_errors == []
    assert requests == reopened_requests == []


@pytest.mark.real
def test_real_standalone_same_start_estimate_keeps_uncertainty_unknown(browser, tmp_path):
    root = os.environ.get("ECNMR_REAL_DATA")
    if not root:
        pytest.skip("Set ECNMR_REAL_DATA for original-data HTML acceptance")
    from ecnmr.server import load_paths
    root = Path(root)
    html = tmp_path / "real.html"
    original = load_paths(next(root.rglob("*.mpr")), root / "4")
    html.write_text(build_html(original), encoding="utf-8")
    page, errors, requests = open_html(browser, html)
    assert page.evaluate("window.ECNMR.experiment.ec.time_s.length") == 98790
    assert page.evaluate("window.ECNMR.experiment.spectra.length") == 64
    alignment = page.evaluate("window.ECNMR.experiment.alignment")
    assert alignment["method"] == "manual"
    assert alignment["assumption"] == "same_start"
    assert alignment["offset_s"] == 0
    assert alignment["uncertainty_s"] is None
    assert page.evaluate("window.ECNMR.experiment.spectra[1].time_s") == pytest.approx(74397 / 64)
    assert page.locator("#series-view").input_value() == "stacked"
    # Same-start timing does not license extrapolation beyond the NMR span.
    page.locator("#time-window").select_option("full")
    page.wait_for_function("document.querySelector('#ec-plot')._fullLayout.yaxis.range[0]>50")
    hover_ec(page, 160000)
    page.wait_for_function("window.ECNMR.currentId===null")
    assert "No NMR" in page.locator("#match-description").inner_text()
    assert not page.evaluate("document.querySelector('#ec-plot').layout.shapes.length")
    page.locator("#time-window").select_option("nmr")
    page.wait_for_function("document.querySelector('#ec-plot')._fullLayout.yaxis.range[0]<22")
    target = hover_ec(page, 30500)
    index = int(target // (74397 / 64))
    expected = page.evaluate("i=>window.ECNMR.experiment.spectra[i].id", index)
    wait_highlight(page, expected)
    # The 1D detail retains every original chemical shift and intensity, even
    # when the shared acquisition overview uses a thinned display trace.
    detail = page.evaluate("""id=>{
      const trace=document.querySelector('#spectrum-plot').data.find(t=>t.meta?.spectrum_id===id);
      return {ppm:Array.from(trace.x),intensity:Array.from(trace.y)};
    }""", expected)
    assert len(detail["ppm"]) == len(detail["intensity"]) == 4096
    assert detail["ppm"] == original["spectra"][index]["ppm"]
    assert detail["intensity"] == original["spectra"][index]["intensity"]
    hover_ec(page, target, click=True)
    page.wait_for_function("window.ECNMR.locked")
    page.locator("#settings-button").click()
    assert page.locator("#uncertainty-input").input_value() == ""
    page.locator("#settings-dialog .dialog-close").first.click()
    screenshot(page, "standalone-real-ux.png")
    page.locator("#series-view").select_option("contour")
    page.wait_for_function("document.querySelector('#heatmap-plot').data[0]?.type==='contour'")
    wait_highlight(page, expected)
    screenshot(page, "standalone-real-contour-ux.png")
    assert not errors
    assert not requests


def test_companion_menus_browser_and_display_commands(browser, tmp_path):
    html = tmp_path / "companion.html"
    html.write_text(build_html(), encoding="utf-8")
    page, errors, requests = open_html(browser, html)
    assert page.locator(".window-identity").inner_text().endswith("TopSpin companion")
    assert page.locator("#browser-spectra .browser-spectrum").count() == 24
    assert page.locator("#data-browser").is_visible()
    page.get_by_test_id("browser-filter").fill("12")
    assert page.locator("#browser-spectra .browser-spectrum:visible").count() == 1
    page.locator("#browser-spectra .browser-spectrum:visible").click()
    page.wait_for_function("window.ECNMR.currentId==='synthetic-12' && window.ECNMR.locked")
    assert "12/24" in page.locator("#status-selection").inner_text()
    page.get_by_test_id("browser-filter").fill("")

    page.get_by_test_id("command-input").fill("contour")
    page.get_by_test_id("command-input").press("Enter")
    page.wait_for_function("document.querySelector('#heatmap-plot').data[0]?.type==='contour'")
    assert "contour · done" in page.locator("#command-response").inner_text()
    page.get_by_test_id("command-input").fill("spectrum 8")
    page.get_by_test_id("command-input").press("Enter")
    page.wait_for_function("window.ECNMR.currentId==='synthetic-08'")
    page.get_by_test_id("command-input").fill("zg")
    page.get_by_test_id("command-input").press("Enter")
    page.wait_for_function("document.querySelector('#command-response').textContent.includes('unavailable')")
    assert page.evaluate("window.ECNMR.currentId") == "synthetic-08"
    assert page.evaluate("window.ECNMR.state.mode") == "offline"

    page.get_by_test_id("workspace-detail").click()
    page.wait_for_function("window.ECNMR.workspaceView==='detail'")
    assert not page.locator(".explorer").is_visible()
    assert page.locator("#spectrum-plot").is_visible()
    with page.expect_download() as download:
        page.get_by_test_id("save-button").click()
    focused_session = tmp_path / "focused-analysis.json"
    download.value.save_as(str(focused_session))
    assert json.loads(focused_session.read_text())["analysis"]["workspace_view"] == "detail"
    page.locator('[data-menu="view"]').click()
    page.get_by_role("menuitem", name="Linked EC–NMR", exact=False).click()
    page.wait_for_function("window.ECNMR.workspaceView==='linked'")
    assert page.locator(".explorer").is_visible()
    page.get_by_test_id("session-file").set_input_files(str(focused_session))
    page.wait_for_function("window.ECNMR.workspaceView==='detail' && window.ECNMR.currentId==='synthetic-08'")
    page.get_by_test_id("workspace-linked").click()
    page.locator('.ribbon-button[data-action="analysis"]').click()
    page.wait_for_function("document.querySelector('#peak-analysis').open && document.querySelector('#peak-plot').data?.[0]?.y?.length===24")
    page.locator("#peak-analysis > summary").click()
    page.locator('.ribbon-button[data-action="browser"]').click()
    assert not page.locator("#data-browser").is_visible()
    page.locator('.ribbon-button[data-action="browser"]').click()
    assert page.locator("#data-browser").is_visible()
    page.locator('[data-menu="help"]').click()
    page.get_by_role("menuitem", name="Controls and commands…", exact=False).click()
    assert page.locator("#help-dialog").is_visible()
    assert "external companion prototype" in page.locator("#help-dialog").inner_text()
    page.keyboard.press("Escape")
    assert not page.locator("#help-dialog").is_visible()
    assert not errors
    assert not requests


def test_companion_popout_restores_the_current_analysis_without_a_service(browser, tmp_path):
    html = tmp_path / "popup-source.html"
    html.write_text(build_html(), encoding="utf-8")
    page, errors, requests = open_html(browser, html)
    page.get_by_test_id("command-input").fill("spectrum 9")
    page.get_by_test_id("command-input").press("Enter")
    page.wait_for_function("window.ECNMR.currentId==='synthetic-09' && window.ECNMR.locked")
    page.locator("#series-view").select_option("contour")
    page.wait_for_function("document.querySelector('#heatmap-plot').data[0]?.type==='contour'")
    with page.expect_popup() as popup_event:
        page.get_by_test_id("popout-button").click()
    popup = popup_event.value
    popup_errors, popup_requests = [], []
    popup.on("pageerror", lambda error: popup_errors.append(str(error)))
    popup.on("request", lambda request: popup_requests.append(request.url) if request.url.startswith(("http:", "https:")) else None)
    popup.wait_for_function("window.ECNMR?.ready && window.ECNMR.currentId==='synthetic-09' && window.ECNMR.locked")
    assert popup.locator("#series-view").input_value() == "contour"
    assert popup.locator("body").evaluate("el=>el.classList.contains('popup-window')")
    assert popup.locator("#browser-spectra .browser-spectrum").count() == 24
    assert popup.evaluate("window.ECNMR.state.mode") == "offline"
    assert not errors
    assert not requests
    assert not popup_errors
    assert not popup_requests
    popup.close()
