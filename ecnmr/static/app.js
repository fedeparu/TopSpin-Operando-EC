/* Shared local/offline renderer. Hover updates only the selected traces; raw data never change. */
"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const fmt = (value, digits = 2) => finite(value) ? value.toLocaleString(undefined, {maximumFractionDigits: digits}) : "—";
  const nfmt = value => finite(value) ? value.toLocaleString() : "—";
  const hours = seconds => finite(seconds) ? `${fmt(seconds / 3600, 3)} h` : "Timing unknown";
  const basename = value => String(value || "").split(/[\\/]/).filter(Boolean).pop() || "Not loaded";
  const safeName = value => String(value || "experiment").replace(/[^a-zA-Z0-9_.-]/g, "_").slice(0, 90);
  const colors = ["#2b837c", "#8c91b1", "#9aaa8b", "#b5a286", "#87aaa7"];
  const coral = "#ca7556";
  const request = window.ECNMR_TRANSPORT || window.fetch.bind(window);
  const ui = {experiment: null, state: null, mode: "offline", selectedIds: new Set(), selectedId: null,
    hoveredId: null, locked: false, ready: false, modeBusy: false, previewLive: false,
    signature: "", pollBusy: false, renderBusy: false, renderPending: false, initialized: false,
    seriesView: "stacked", gain: 0.7, timeRange: null, ppmRange: null, focusRange: null,
    peakRows: [], analysisTimer: null, toastTimer: null, lastError: "", syncing: false,
    frame: null, hoverCandidate: null, highlightBusy: false, highlightPending: false,
    spectrumMap: new Map(), pointCache: new Map(), globalMax: 1, spacing: 1, timed: false,
    seriesHighlightIndex: null, detailMainIndex: 0, sourceCount: 0, noAcquisition: false};
  window.ECNMR = {
    get experiment() { return ui.experiment; }, get state() { return ui.state; },
    get selectedIds() { return new Set(ui.selectedIds); }, get selectedId() { return ui.selectedId; },
    get hoveredId() { return ui.hoveredId; }, get currentId() { return ui.noAcquisition && !ui.locked ? null : ui.hoveredId || ui.selectedId; },
    get locked() { return ui.locked; }, get ready() { return ui.ready; },
    setSelection: (id, overlay = false) => selectSpectrum(id, overlay), refresh: () => refresh(true),
  };
  const config = {responsive: true, displaylogo: false, scrollZoom: true,
    modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "hoverCompareCartesian", "hoverClosestCartesian"]};
  const plotFont = {family: 'Inter, "Segoe UI", Arial, sans-serif', size: 11, color: "#76857c"};
  const axis = () => ({gridcolor: "#edf1ed", zerolinecolor: "#e4ebe4", showline: false, ticks: "", tickfont: {size: 10},
    title: {font: {size: 11}, standoff: 12}, automargin: false});
  const layout = key => ({font: {...plotFont}, paper_bgcolor: "#fff", plot_bgcolor: "#fff", showlegend: false,
    margin: {l: 62, r: 22, t: 12, b: 47}, hovermode: "closest", dragmode: "zoom",
    hoverlabel: {font: {size: 11}, bgcolor: "#fff", bordercolor: "#dce5dd"},
    uirevision: `${ui.experiment?.id || "empty"}:${key}`, xaxis: axis(), yaxis: axis()});
  const isAligned = () => ui.experiment && ui.experiment.alignment?.method !== "unaligned";
  const timeOf = s => isAligned() && finite(s.time_s) ? s.time_s + (ui.experiment.alignment.offset_s || 0) : null;
  const durationOf = s => finite(s.duration_s) && s.duration_s >= 0 ? s.duration_s : null;
  const representativeTime = s => finite(timeOf(s)) ? timeOf(s) + (durationOf(s) || 0) / 2 : null;
  const currentSpectrum = () => ui.spectrumMap.get(ui.hoveredId || ui.selectedId);
  const spectrumColor = id => colors[Math.max(0, ui.experiment?.spectra.findIndex(s => s.id === id) || 0) % colors.length];
  const rowTime = (s, i) => ui.timed ? representativeTime(s) / 3600 : i + 1;
  const emptyAnnotation = text => [{text, x: 0.5, y: 0.5, xref: "paper", yref: "paper", showarrow: false, font: {size: 12, color: "#98a494"}}];
  const jsonRequest = (method, body) => ({method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  async function api(path, options = {}) {
    const response = await request(path, options);
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try { const body = await response.json(); message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || body); } catch (_) {}
      throw new Error(message);
    }
    return response.status === 204 ? null : response.json();
  }
  function toast(message, error = false) {
    $("toast").textContent = message; $("toast").classList.toggle("error", error); $("toast").hidden = false;
    clearTimeout(ui.toastTimer); ui.toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 10000 : 4500);
  }
  async function withBusy(label, work) {
    $("busy-label").textContent = label; $("busy-overlay").hidden = false;
    try { return await work(); } catch (error) { toast(error.message, true); return null; }
    finally { $("busy-overlay").hidden = true; }
  }
  function signature(state) { return [state.mode, state.state, state.available_ec, state.available_spectra, state.revision ?? ""].join("|"); }
  async function refresh(force = false) {
    if (ui.pollBusy) return;
    ui.pollBusy = true;
    try {
      ui.state = await api("/api/state");
      if (!ui.modeBusy && !ui.previewLive) ui.mode = ui.state.mode || ui.mode;
      const next = signature(ui.state);
      if (force || next !== ui.signature || !ui.experiment) {
        const exp = await api("/api/experiment"), fresh = !ui.experiment || ui.experiment.id !== exp.id;
        const oldCount = ui.experiment?.spectra.length || 0;
        ui.experiment = exp; ui.signature = next;
        if (fresh || force) { restoreAnalysis(exp.analysis || {}, fresh); restoreAlignmentInputs(exp); }
        prepareData(fresh);
        const ids = new Set(exp.spectra.map(s => s.id));
        ui.selectedIds = new Set([...ui.selectedIds].filter(id => ids.has(id)));
        if (!ids.has(ui.selectedId)) ui.selectedId = null;
        if (!ids.has(ui.hoveredId)) ui.hoveredId = null;
        if (exp.spectra.length && !ui.selectedId) { ui.selectedId = exp.spectra[0].id; ui.selectedIds.add(ui.selectedId); }
        if (!fresh && exp.spectra.length > oldCount && ui.mode === "simulation" && $("follow-latest").checked && !ui.locked) {
          ui.selectedId = exp.spectra.at(-1).id; ui.hoveredId = null;
          if (ui.selectedIds.size <= 1) ui.selectedIds = new Set([ui.selectedId]);
        }
        await render();
      }
      renderState(); $("connection-label").textContent = window.ECNMR_TRANSPORT ? "Running in this browser" : "Local service connected"; ui.lastError = "";
    } catch (error) {
      $("connection-label").textContent = "Service unavailable · retrying";
      if (error.message !== ui.lastError) toast(error.message, true); ui.lastError = error.message;
    } finally { ui.pollBusy = false; }
  }
  function restoreAnalysis(settings, fresh) {
    if (Array.isArray(settings.selected_ids)) ui.selectedIds = new Set(settings.selected_ids); else if (fresh) ui.selectedIds.clear();
    if (settings.selected_id) ui.selectedId = settings.selected_id; else if (fresh) ui.selectedId = [...ui.selectedIds][0] || null;
    if (finite(settings.peak_min)) $("peak-min").value = settings.peak_min;
    if (finite(settings.peak_max)) $("peak-max").value = settings.peak_max;
    if (settings.x_axis) $("peak-axis").value = settings.x_axis;
    if (settings.peak_metric) $("peak-metric").value = settings.peak_metric;
    if (["potential", "current", "capacity"].includes(settings.ec_view)) $("ec-view").value = settings.ec_view;
    if (typeof settings.follow_latest === "boolean") $("follow-latest").checked = settings.follow_latest;
    if (fresh) { ui.hoveredId = null; ui.noAcquisition = false; ui.locked = settings.locked === true; ui.timeRange = null; ui.ppmRange = null; }
    if (["stacked", "contour", "map"].includes(settings.series_view)) ui.seriesView = settings.series_view; else if (fresh) ui.seriesView = "stacked";
    if (finite(settings.gain) && settings.gain >= 0.15 && settings.gain <= 3) ui.gain = settings.gain; else if (fresh) ui.gain = 0.7;
    if (Array.isArray(settings.time_range) && settings.time_range.length === 2 && settings.time_range.every(finite)) ui.timeRange = settings.time_range;
    if (Array.isArray(settings.ppm_range) && settings.ppm_range.length === 2 && settings.ppm_range.every(finite)) ui.ppmRange = settings.ppm_range;
    if (["nmr", "full"].includes(settings.time_window)) $("time-window").value = settings.time_window; else if (fresh) $("time-window").value = "nmr";
    $("series-view").value = ui.seriesView; $("gain-input").value = ui.gain; $("gain-value").textContent = `${ui.gain.toFixed(2)}×`;
  }
  function restoreAlignmentInputs(exp) {
    const a = exp.alignment || {}, ds = exp.spectra.map(s => s.duration_s);
    const duration = ds.length && ds.every(d => finite(d) && d === ds[0]) ? ds[0] : null;
    $("offset-input").value = finite(a.offset_s) ? a.offset_s : 0;
    $("interval-input").value = finite(a.assumed_interval_s) ? a.assumed_interval_s : "";
    $("duration-input").value = finite(duration) ? duration : "";
    $("uncertainty-input").value = finite(a.uncertainty_s) ? a.uncertainty_s : "";
  }
  function prepareData(fresh) {
    const spectra = ui.experiment.spectra; ui.spectrumMap = new Map(spectra.map(s => [s.id, s]));
    ui.timed = !!spectra.length && isAligned() && spectra.every(s => finite(representativeTime(s)));
    if (fresh) { ui.pointCache.clear(); ui.globalMax = 0; }
    let strongest = spectra[0], peakIndex = 0, strength = -Infinity;
    for (const s of spectra) {
      for (let i = 0; i < s.intensity.length; i++) {
        const value = Math.abs(s.intensity[i]);
        ui.globalMax = Math.max(ui.globalMax, value);
        if (value > strength) { strength = value; strongest = s; peakIndex = i; }
      }
    }
    ui.globalMax = ui.globalMax || 1;
    if (strongest) {
      const center = strongest.ppm[peakIndex], max = Math.max(strongest.ppm[0], strongest.ppm.at(-1)), min = Math.min(strongest.ppm[0], strongest.ppm.at(-1));
      const half = Math.min(40, (max - min) / 2), rounded = Math.abs(center) < 8 ? 0 : center;
      ui.focusRange = [Math.min(max, rounded + half), Math.max(min, rounded - half)];
      if (!ui.ppmRange) ui.ppmRange = [...ui.focusRange];
    }
    const times = spectra.map(rowTime), gaps = times.slice(1).map((t, i) => Math.abs(t - times[i])).filter(t => t > 0).sort((a, b) => a - b);
    ui.spacing = gaps.length ? gaps[Math.floor(gaps.length / 2)] : ui.timed ? Math.max((durationOf(spectra[0]) || 300) / 3600, 0.01) : 1;
    if (!ui.timeRange) ui.timeRange = defaultTimeRange();
  }
  function defaultTimeRange() {
    const exp = ui.experiment, spectra = exp.spectra;
    let low = 0, high = exp.ec.time_s.length ? exp.ec.time_s.at(-1) / 3600 : 1;
    if ($("time-window").value === "nmr" && ui.timed) {
      low = Math.min(...spectra.map(s => timeOf(s))) / 3600;
      high = Math.max(...spectra.map(s => timeOf(s) + (durationOf(s) || 0))) / 3600;
    }
    const pad = Math.max((high - low) * 0.008, ui.timed ? ui.spacing * 0.12 : 0.02);
    return [Math.max(high, low + 0.01) + pad, low - pad];
  }
  function analysis() {
    return {selected_ids: [...ui.selectedIds], selected_id: ui.selectedId, locked: ui.locked,
      peak_min: Number($("peak-min").value), peak_max: Number($("peak-max").value), x_axis: $("peak-axis").value,
      peak_metric: $("peak-metric").value, ec_view: $("ec-view").value, follow_latest: $("follow-latest").checked,
      series_view: ui.seriesView, gain: ui.gain, time_range: ui.timeRange, ppm_range: ui.ppmRange, time_window: $("time-window").value};
  }
  function queueAnalysisSave() { clearTimeout(ui.analysisTimer); ui.analysisTimer = setTimeout(() => saveAnalysis().catch(e => toast(e.message, true)), 500); }
  async function saveAnalysis() { clearTimeout(ui.analysisTimer); await api("/api/analysis", jsonRequest("PUT", analysis())); }
  function renderState() {
    const state = ui.state || {}, running = state.state === "running", paused = ["paused", "disconnected"].includes(state.state);
    document.querySelectorAll(".mode-button").forEach(b => { const active = b.dataset.mode === ui.mode; b.classList.toggle("active", active); b.setAttribute("aria-selected", String(active)); });
    $("acquisition-panel").hidden = ui.mode === "offline"; $("simulation-controls").hidden = ui.mode !== "simulation"; $("live-notice").hidden = ui.mode !== "live";
    $("run-state").textContent = ui.mode === "live" ? "Hardware disabled" : state.state || "ready"; $("run-dot").className = `status-dot ${state.state || ""}`;
    $("acquisition-status").textContent = state.state || "ready"; $("start-button").disabled = state.state !== "ready"; $("prepare-button").disabled = running;
    $("pause-button").disabled = !running && !paused; $("pause-button").textContent = paused ? "▶ Resume" : "Ⅱ Pause";
    $("stop-button").disabled = !running && !paused; $("disconnect-button").disabled = !running; $("reconnect-button").disabled = !paused; $("fail-button").disabled = !running; $("speed-select").disabled = running || paused;
    $("event-label").textContent = state.event_count ? `${state.event_count} acquisition events` : "No hardware activated";
    if (ui.mode === "simulation") $("metric-time").textContent = `${fmt((state.elapsed_s || 0) / 3600, 2)} h replay`;
    if (state.error) { $("notice-banner").hidden = false; $("notice-text").textContent = state.error; $("notice-details").hidden = true; }
  }
  function renderInfo() {
    const exp = ui.experiment, ec = exp.ec, spectra = exp.spectra, a = exp.alignment || {}, synthetic = exp.metadata?.synthetic || a.method === "synthetic";
    $("experiment-title").textContent = exp.name || "EC–NMR experiment";
    $("experiment-subtitle").textContent = synthetic ? "Synthetic cycling experiment" : "Experimental measurements";
    $("data-badge").textContent = synthetic ? "SYNTHETIC" : "EXPERIMENTAL"; $("data-badge").classList.toggle("real", !synthetic);
    $("metric-ec").textContent = nfmt(ec.time_s.length); $("metric-spectra").textContent = nfmt(spectra.length);
    $("metric-time").textContent = ec.time_s.length ? `${fmt(ec.time_s.at(-1) / 3600)} h EC` : "Waiting for data";
    const derived = /derived|reconstructed/i.test(ec.metadata?.current_method || ""), signed = /signed|Q-Qo/.test(`${ec.metadata?.capacity_method || ""} ${ec.metadata?.capacity_column || ""}`);
    $("ec-view").querySelector('[value="current"]').textContent = derived ? "Derived current / mA" : "Current / mA";
    $("ec-view").querySelector('[value="capacity"]').textContent = signed ? "Signed charge / mAh" : "Capacity / mAh";
    $("peak-axis").querySelector('[value="capacity"]').textContent = signed ? "Signed charge / mAh" : "Capacity / mAh";
    $("ec-source").textContent = basename(ec.source); $("ec-source").title = ec.source || "";
    $("nmr-source").textContent = spectra.length ? `${spectra.length} spectra · ${basename(spectra[0].source)}` : "No completed spectra yet";
    $("metric-nucleus").textContent = spectra.length ? `${spectra[0].metadata?.nucleus || "NMR"} · ${nfmt(spectra[0].ppm.length)} points per spectrum` : "";
    $("metric-ec-detail").textContent = [ec.metadata?.current_method, ec.metadata?.capacity_method || ec.metadata?.capacity_basis].filter(Boolean).join(". ");
    $("metric-time-detail").textContent = `Original EC start: ${ec.start_time || "unknown"}. Original NMR dates are retained below.`;
    const same = a.assumption === "same_start", aligned = a.method !== "unaligned";
    $("timing-chip").textContent = same ? "Started together · row times estimated" : a.method === "synthetic" ? "Synthetic clock · timing known" : a.method === "manual" ? "Manual alignment · timing assumed" : a.method === "metadata" ? "Metadata alignment" : "Timing unaligned";
    $("timing-chip").classList.toggle("assumed", a.method === "manual"); $("alignment-status").textContent = same ? "Same-start assumption" : a.method || "unknown";
    $("alignment-summary").textContent = same ? "Both starts are assigned zero. Row times are estimated uniformly from the recorded whole NMR duration; variable delays and true synchronization are unverified. Timing uncertainty is unknown." : !aligned ? "No verified common timeline. Define an explicit assumption to link the recordings." : `${a.method} alignment; offset ${fmt(a.offset_s, 3)} s. ${finite(a.uncertainty_s) ? `Uncertainty ±${fmt(a.uncertainty_s)} s.` : "Timing uncertainty is unknown."}`;
    $("settings-provenance").textContent = JSON.stringify({alignment: a, ec_start_time: ec.start_time, nmr: exp.metadata, warnings: exp.warnings}, null, 2);
    $("notice-banner").hidden = aligned; $("notice-text").textContent = "NMR row times are unavailable. Open Timing settings to align the recordings explicitly."; $("notice-details").hidden = false;
    $("series-caption").textContent = ui.timed ? "Experiment time increases downward · shared zoom & pan" : "NMR acquisition order only · timing unaligned";
    $("series-scale-caption").textContent = ui.seriesView === "stacked" ? "Display offsets only · one global amplitude scale" : "Coral trace = current 1D spectrum at its acquisition time";
    $("nmr-series-title").textContent = `${spectra[0]?.metadata?.nucleus || "NMR"} · ${{stacked: "stacked spectra", contour: "contour view", map: "intensity map"}[ui.seriesView]}`;
    $("overlay-count").textContent = `${ui.selectedIds.size} selected`; renderState(); renderSelectionLabels();
  }
  function renderSelectionLabels() {
    const s = currentSpectrum(), index = s ? ui.experiment.spectra.indexOf(s) : -1;
    $("metric-selected").textContent = s ? `${index + 1} / ${ui.experiment.spectra.length}` : "—";
    $("metric-selection-time").textContent = s ? finite(timeOf(s)) ? `${hours(timeOf(s))}${durationOf(s) !== null ? ` – ${hours(timeOf(s) + durationOf(s))}` : " · duration unknown"}` : "Timing unknown" : "Waiting for completed spectra";
    $("selection-state").textContent = ui.locked ? "Locked" : ui.noAcquisition ? "Outside NMR window" : ui.hoveredId ? "Hover preview" : "Hover to explore"; $("selection-state").classList.toggle("locked", ui.locked);
    $("unlock-button").disabled = !ui.locked; $("spectrum-select").value = s?.id || ""; $("spectrum-slider").value = Math.max(index, 0);
    $("spectrum-slider-label").textContent = s ? `${index + 1} / ${ui.experiment.spectra.length}` : "—";
    $("previous-spectrum").disabled = index <= 0; $("next-spectrum").disabled = index < 0 || index >= ui.experiment.spectra.length - 1;
    $("spectrum-caption").textContent = s ? `${s.label || `Spectrum ${index + 1}`} · original intensity values · no normalization` : "No completed acquisition yet";
    $("match-description").textContent = ui.locked ? `Spectrum ${index + 1} locked. Choose Unlock hover to explore freely.` : ui.noAcquisition ? "No NMR acquired at this time. The detail pane retains the last pinned spectrum." : ui.hoveredId ? `Previewing spectrum ${index + 1}. Click either plot to lock it.` : "Hover either plot to inspect a spectrum. Click to lock it.";
    document.querySelectorAll(".spectrum-row").forEach(row => row.classList.toggle("selected", row.dataset.spectrumId === s?.id));
  }
  function renderNavigation() {
    const select = $("spectrum-select"), fragment = document.createDocumentFragment();
    ui.experiment.spectra.forEach((s, i) => { const option = document.createElement("option"); option.value = s.id; option.textContent = `${String(i + 1).padStart(2, "0")} · ${ui.timed ? hours(representativeTime(s)) : s.label || "timing unknown"}`; fragment.append(option); });
    select.replaceChildren(fragment); $("spectrum-slider").max = Math.max(ui.experiment.spectra.length - 1, 0); select.disabled = !ui.experiment.spectra.length; $("spectrum-slider").disabled = !ui.experiment.spectra.length;
    renderList(); renderSelectionLabels();
  }
  function renderList() {
    const list = $("spectrum-list"), oldScroll = list.scrollTop, fragment = document.createDocumentFragment();
    ui.experiment.spectra.forEach((s, i) => {
      const row = document.createElement("div"); row.className = "spectrum-row"; row.dataset.spectrumId = s.id; row.dataset.testid = "spectrum-row";
      const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.checked = ui.selectedIds.has(s.id); checkbox.dataset.testid = "overlay-checkbox"; checkbox.setAttribute("aria-label", `Overlay ${s.label || `spectrum ${i + 1}`}`);
      checkbox.addEventListener("change", () => toggleOverlay(s.id));
      const button = document.createElement("button"); button.type = "button"; button.dataset.testid = "spectrum-select"; button.textContent = `${s.label || `Spectrum ${i + 1}`} · ${ui.timed ? hours(representativeTime(s)) : "timing unknown"}`; button.addEventListener("click", () => selectSpectrum(s.id));
      row.append(checkbox, button); fragment.append(row);
    }); list.replaceChildren(fragment); list.scrollTop = oldScroll;
  }
  async function render() {
    if (ui.renderBusy) { ui.renderPending = true; return; }
    if (!ui.experiment || !window.Plotly) return;
    ui.renderBusy = true;
    try {
      renderInfo(); renderNavigation();
      await Promise.all([renderEC(), renderSeries(), renderSpectra(), $("peak-analysis").open ? renderPeak() : Promise.resolve()]);
      if (!ui.initialized) { attachPlotEvents(); ui.initialized = true; }
      ui.ready = true;
    } finally { ui.renderBusy = false; if (ui.renderPending) { ui.renderPending = false; await render(); } }
  }
  function thin(x, y, limit = 1800) {
    if (x.length <= limit) return {x, y};
    const xx = [], yy = [], step = Math.ceil(x.length / (limit / 2));
    for (let i = 0; i < x.length; i += step) {
      let min = i, max = i; for (let j = i + 1; j < Math.min(i + step, x.length); j++) { if (y[j] < y[min]) min = j; if (y[j] > y[max]) max = j; }
      for (const j of min === max ? [min] : [min, max].sort((a, b) => a - b)) { xx.push(x[j]); yy.push(y[j]); }
    } return {x: xx, y: yy};
  }
  function displayPoints(s) {
    const key = `${s.id}:${ui.ppmRange?.join(",")}`, cached = ui.pointCache.get(key); if (cached) return cached;
    const low = Math.min(...ui.ppmRange), high = Math.max(...ui.ppmRange), x = [], y = [];
    for (let i = 0; i < s.ppm.length; i++) if (s.ppm[i] >= low && s.ppm[i] <= high) { x.push(s.ppm[i]); y.push(s.intensity[i]); }
    const points = thin(x.length > 1 ? x : s.ppm, y.length > 1 ? y : s.intensity, 900); ui.pointCache.set(key, points); return points;
  }
  function selectionShape(vertical = true) {
    const s = currentSpectrum(); if (!s || !ui.timed || ui.noAcquisition && !ui.locked) return [];
    const start = timeOf(s) / 3600, end = (timeOf(s) + (durationOf(s) || 0)) / 3600;
    return [{type: "rect", xref: "paper", yref: "y", x0: 0, x1: 1, y0: start, y1: end, fillcolor: "#ca755610", line: {width: 0}, layer: "below"},
      {type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: representativeTime(s) / 3600, y1: representativeTime(s) / 3600, line: {color: "#d9ac95", width: 1, dash: "dot"}}];
  }
  async function renderEC() {
    const ec = ui.experiment.ec, quantity = $("ec-view").value;
    const values = quantity === "current" ? ec.current_mA : quantity === "capacity" ? ec.capacity_mAh : ec.voltage_V;
    const data = thin(ec.time_s.map(t => t / 3600), values || [], 5000);
    const l = layout("ec"), narrow = $("ec-plot").clientWidth < 180;
    l.margin = {l: narrow ? 43 : 62, r: narrow ? 8 : 18, t: 12, b: 47}; l.xaxis.nticks = narrow ? 3 : 5;
    l.xaxis.title.text = $("ec-view").selectedOptions[0].textContent; l.yaxis.title.text = "Experiment time / h";
    l.yaxis.range = ui.timeRange; l.yaxis.autorange = false; l.shapes = selectionShape();
    const traces = values?.some(finite) ? [{type: "scatter", mode: "lines", x: data.y, y: data.x, name: l.xaxis.title.text,
      line: {color: "#3e827b", width: 1.5}, hoverinfo: "skip", meta: {kind: "electrochemistry"}}] : [];
    if (!traces.length) l.annotations = emptyAnnotation("Waiting for EC data");
    await Plotly.react("ec-plot", traces, l, config);
  }
  function selectedSeriesTrace() {
    const s = currentSpectrum(); if (!s || ui.noAcquisition && !ui.locked) return {x: [], y: [], customdata: [], meta: {kind: "selected-spectrum"}};
    const points = displayPoints(s), i = ui.experiment.spectra.indexOf(s), baseline = rowTime(s, i), scale = ui.spacing * ui.gain * 0.85 / ui.globalMax;
    return {x: points.x, y: points.y.map(value => baseline - value * scale), customdata: points.x.map(() => s.id), meta: {kind: "selected-spectrum", spectrum_id: s.id}};
  }
  async function renderSeries() {
    const spectra = ui.experiment.spectra, l = layout("series"); l.margin = {l: 12, r: 25, t: 12, b: 47};
    l.xaxis.title.text = "Chemical shift / ppm"; l.xaxis.range = ui.ppmRange; l.xaxis.autorange = false;
    l.yaxis.range = ui.timed ? ui.timeRange : [spectra.length + 0.6, 0.4]; l.yaxis.autorange = false; l.yaxis.showticklabels = !ui.timed; l.yaxis.showgrid = true;
    if (!ui.timed) l.yaxis.title.text = "Acquisition order";
    const traces = [];
    if (spectra.length && ui.seriesView === "stacked") {
      const x = [], y = [], customdata = [], scale = ui.spacing * ui.gain * 0.85 / ui.globalMax;
      spectra.forEach((s, i) => { const points = displayPoints(s), baseline = rowTime(s, i);
        x.push(...points.x, null); y.push(...points.y.map(value => baseline - value * scale), null); customdata.push(...points.x.map(() => s.id), null); });
      traces.push({type: "scatter", mode: "lines", x, y, customdata, line: {color: "#8aa7a1", width: 0.8}, hoverinfo: "skip", name: "Acquisition series", meta: {kind: "stacked-background"}});
    } else if (spectra.length) {
      const first = spectra[0], low = Math.min(...ui.ppmRange), high = Math.max(...ui.ppmRange);
      const indices = first.ppm.map((v, i) => v >= low && v <= high ? i : -1).filter(i => i >= 0), step = Math.max(1, Math.ceil(indices.length / 450));
      const cols = indices.filter((_, i) => i % step === 0), common = spectra.every(s => s.ppm.length === first.ppm.length && s.ppm[0] === first.ppm[0] && s.ppm.at(-1) === first.ppm.at(-1));
      if (common) {
        const max = ui.globalMax / ui.gain, z = spectra.map(s => cols.map(i => s.intensity[i]));
        traces.push({type: ui.seriesView === "contour" ? "contour" : "heatmap", x: cols.map(i => first.ppm[i]), y: spectra.map(rowTime), z,
          colorscale: [[0, "#fff"], [0.08, "#f0f5ef"], [0.3, "#bbd4c9"], [0.6, "#6ba59b"], [1, "#2b7a72"]],
          zmin: 0, zmax: max, showscale: false, hoverinfo: "skip", name: "Intensity",
          ...(ui.seriesView === "contour" ? {contours: {coloring: "lines", showlabels: false, start: max * 0.05, end: max, size: max / 12}, line: {width: 0.9}, autocontour: false} : {})});
      } else l.annotations = emptyAnnotation("This view requires a shared chemical-shift axis");
    }
    ui.seriesHighlightIndex = traces.length;
    traces.push({type: "scatter", mode: "lines", ...selectedSeriesTrace(), line: {color: coral, width: 1.8}, hoverinfo: "skip", name: "Current spectrum"});
    if (!spectra.length) l.annotations = emptyAnnotation("Completed NMR spectra will appear here");
    l.shapes = selectionShape();
    await Plotly.react("heatmap-plot", traces, l, config);
  }
  async function renderSpectra() {
    const s = currentSpectrum(), extra = ui.experiment.spectra.filter(row => ui.selectedIds.has(row.id) && row.id !== s?.id);
    const traces = extra.map(row => ({type: "scatter", mode: "lines", x: row.ppm, y: row.intensity, name: row.label || row.id, line: {color: spectrumColor(row.id), width: 1.1}, hovertemplate: "%{x:.4f} ppm<br>%{y:.6g}<extra></extra>", meta: {spectrum_id: row.id}}));
    ui.detailMainIndex = traces.length;
    traces.push({type: "scatter", mode: "lines", x: s ? s.ppm : [], y: s ? s.intensity : [],
      name: s?.label || "Current spectrum", line: {color: coral, width: 1.6}, hovertemplate: "%{x:.4f} ppm<br>%{y:.6g}<extra></extra>", meta: {spectrum_id: s?.id}});
    const l = layout("detail"); l.margin = {l: 64, r: 25, t: 12, b: 43}; l.xaxis.title.text = "Chemical shift / ppm";
    l.xaxis.range = ui.ppmRange; l.xaxis.autorange = false; l.yaxis.title.text = "Intensity / a.u.";
    l.showlegend = extra.length > 0; l.legend = {orientation: "h", x: 0, y: 1.12, font: {size: 9}, itemsizing: "constant"};
    if (!s) l.annotations = emptyAnnotation("Waiting for a completed NMR spectrum");
    await Plotly.react("spectrum-plot", traces, l, config);
  }
  function candidateAt(timeH) {
    if (ui.timed && ui.experiment.spectra.length) {
      const starts = ui.experiment.spectra.map(s => timeOf(s) / 3600);
      const ends = ui.experiment.spectra.map(s => (timeOf(s) + (durationOf(s) || 0)) / 3600);
      if (timeH < Math.min(...starts) || timeH > Math.max(...ends)) return null;
    }
    let result = null, distance = Infinity;
    ui.experiment.spectra.forEach((s, i) => { const d = Math.abs(rowTime(s, i) - timeH); if (d < distance) { distance = d; result = s.id; } });
    return result;
  }
  function scheduleHover(id) {
    if (ui.locked || id === undefined) return;
    if (id === null) {
      if (ui.frame) { cancelAnimationFrame(ui.frame); ui.frame = null; }
      ui.hoverCandidate = null;
      if (!ui.noAcquisition) { ui.hoveredId = null; ui.noAcquisition = true; updateHighlight(); }
      return;
    }
    if (!ui.noAcquisition && id === (ui.hoveredId || ui.selectedId)) return;
    ui.hoverCandidate = id; if (ui.frame) return;
    ui.frame = requestAnimationFrame(() => { ui.frame = null; if (ui.locked) return; ui.noAcquisition = false; ui.hoveredId = ui.hoverCandidate; updateHighlight(); });
  }
  async function updateHighlight() {
    if (!ui.ready) return;
    if (ui.highlightBusy || ui.renderBusy) { ui.highlightPending = true; return; }
    ui.highlightBusy = true;
    try {
      renderSelectionLabels(); const s = currentSpectrum(), overlay = selectedSeriesTrace();
      if (ui.seriesHighlightIndex !== null && $("heatmap-plot").data?.[ui.seriesHighlightIndex])
        await Plotly.restyle("heatmap-plot", {x: [overlay.x], y: [overlay.y], customdata: [overlay.customdata], meta: [overlay.meta]}, [ui.seriesHighlightIndex]);
      if (s && $("spectrum-plot").data?.[ui.detailMainIndex]) {
        await Plotly.restyle("spectrum-plot", {x: [s.ppm], y: [s.intensity], name: [s.label || s.id], meta: [{spectrum_id: s.id}]}, [ui.detailMainIndex]);
      }
      await Promise.all([Plotly.relayout("ec-plot", {shapes: selectionShape()}), Plotly.relayout("heatmap-plot", {shapes: selectionShape()})]);
    } finally { ui.highlightBusy = false; if (ui.highlightPending) { ui.highlightPending = false; updateHighlight(); } }
  }
  function pointerId(plot, event) {
    const l = plot._fullLayout; if (!l || !ui.experiment?.spectra.length) return undefined;
    const box = plot.getBoundingClientRect(), x = event.clientX - box.left - l.xaxis._offset, y = event.clientY - box.top - l.yaxis._offset;
    if (x < 0 || x > l.xaxis._length || y < 0 || y > l.yaxis._length) return undefined;
    if (plot.id === "ec-plot" && !ui.timed) return null;
    return candidateAt(l.yaxis.p2d(y));
  }
  function attachPlotEvents() {
    [$("ec-plot"), $("heatmap-plot")].forEach(plot => {
      plot.addEventListener("mousemove", event => { if (!(event.buttons & 1)) scheduleHover(pointerId(plot, event)); });
      plot.addEventListener("mouseleave", () => {
        if (ui.locked) return;
        if (ui.frame) { cancelAnimationFrame(ui.frame); ui.frame = null; }
        ui.hoverCandidate = null;
        if (ui.hoveredId || ui.noAcquisition) { ui.hoveredId = null; ui.noAcquisition = false; updateHighlight(); }
      });
      let down = null;
      plot.addEventListener("mousedown", event => { down = {x: event.clientX, y: event.clientY}; });
      plot.addEventListener("click", event => {
        if (down && Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5) return;
        if (event.target.closest(".modebar")) return;
        const id = pointerId(plot, event); if (id) selectSpectrum(id);
      });
      plot.on("plotly_hover", event => { const point = event.points?.[0]; if (!point) return; scheduleHover(typeof point.customdata === "string" ? point.customdata : candidateAt(point.y)); });
      plot.on("plotly_relayout", event => syncAxes(plot, event));
    });
    $("spectrum-plot").on("plotly_relayout", event => syncPPM($("spectrum-plot"), event));
    $("peak-plot").on?.("plotly_click", event => { const id = event.points?.[0]?.customdata; if (id) selectSpectrum(id); });
  }
  async function syncAxes(source, event) {
    if (ui.syncing) return;
    const range = event["yaxis.range"] || (finite(event["yaxis.range[0]"]) && finite(event["yaxis.range[1]"]) ? event["yaxis.range"] || [event["yaxis.range[0]"], event["yaxis.range[1]"]] : null);
    if (range && ui.timed) {
      ui.timeRange = range;
      const other = source.id === "ec-plot" ? $("heatmap-plot") : $("ec-plot");
      if (other.layout?.yaxis?.range?.some((v, i) => Math.abs(v - range[i]) > 1e-9)) {
        ui.syncing = true; try { await Plotly.relayout(other, {"yaxis.range": range, "yaxis.autorange": false}); } finally { ui.syncing = false; }
      }
      queueAnalysisSave();
    } else if (event["yaxis.autorange"] === true && ui.timed) { ui.timeRange = defaultTimeRange(); await setTimeRange(); }
    if (source.id === "heatmap-plot") await syncPPM(source, event);
  }
  async function syncPPM(source, event) {
    if (ui.syncing) return;
    const range = event["xaxis.range"] || (finite(event["xaxis.range[0]"]) && finite(event["xaxis.range[1]"]) ? event["xaxis.range"] || [event["xaxis.range[0]"], event["xaxis.range[1]"]] : null);
    if (!range) return;
    ui.ppmRange = range;
    const other = source.id === "heatmap-plot" ? $("spectrum-plot") : $("heatmap-plot");
    ui.syncing = true; try { await Plotly.relayout(other, {"xaxis.range": range, "xaxis.autorange": false}); } finally { ui.syncing = false; }
    queueAnalysisSave();
  }
  async function setTimeRange() {
    ui.syncing = true;
    try { await Promise.all([Plotly.relayout("ec-plot", {"yaxis.range": ui.timeRange, "yaxis.autorange": false}), ui.timed ? Plotly.relayout("heatmap-plot", {"yaxis.range": ui.timeRange, "yaxis.autorange": false}) : Promise.resolve()]); }
    finally { ui.syncing = false; } queueAnalysisSave();
  }
  async function selectSpectrum(id, overlay = false) {
    if (!ui.spectrumMap.has(id)) return;
    ui.selectedId = id; ui.hoveredId = null; ui.noAcquisition = false; ui.locked = true;
    if (overlay) ui.selectedIds.add(id); else ui.selectedIds = new Set([id]);
    if (ui.state?.state === "running") $("follow-latest").checked = false;
    renderNavigation(); await renderSpectra(); await updateHighlight(); queueAnalysisSave();
  }
  async function toggleOverlay(id) {
    if (ui.selectedIds.has(id)) ui.selectedIds.delete(id); else ui.selectedIds.add(id);
    renderInfo(); await renderSpectra(); queueAnalysisSave();
  }
  function nearestEC(t) {
    const ec = ui.experiment.ec, times = ec.time_s;
    if (!finite(t) || !times.length || t < times[0] || t > times.at(-1)) return null;
    let left = 0, right = times.length - 1;
    while (left < right) { const middle = (left + right) >>> 1; if (times[middle] < t) left = middle + 1; else right = middle; }
    let index = left;
    if (left > 0 && Math.abs(times[left - 1] - t) < Math.abs(times[left] - t)) index = left - 1;
    return {time_s: times[index], delta_s: times[index] - t, voltage_V: ec.voltage_V?.[index], current_mA: ec.current_mA?.[index], capacity_mAh: ec.capacity_mAh?.[index]};
  }
  function peakValue(s, low, high, metric) {
    const count = s.ppm.length, ascending = s.ppm[0] < s.ppm.at(-1);
    const x = i => s.ppm[ascending ? i : count - 1 - i];
    const y = i => s.intensity[ascending ? i : count - 1 - i];
    if (low < x(0) || high > x(count - 1) || low >= high) return null;
    let first = 0;
    while (first < count - 1 && x(first + 1) <= low) first++;
    const interpolate = (i, bound) => y(i) + (y(i + 1) - y(i)) * (bound - x(i)) / (x(i + 1) - x(i));
    let previousX = low, previousY = interpolate(Math.min(first, count - 2), low);
    let integral = 0, maximum = -Infinity, samples = 0, i = first + 1;
    for (; i < count && x(i) < high; i++) {
      if (x(i) > low) { integral += (x(i) - previousX) * (y(i) + previousY) / 2; previousX = x(i); previousY = y(i); }
      if (x(i) >= low) { maximum = Math.max(maximum, y(i)); samples++; }
    }
    const endY = interpolate(Math.min(Math.max(i - 1, 0), count - 2), high);
    integral += (high - previousX) * (endY + previousY) / 2;
    if (metric === "intensity") {
      // Maximum intensity uses measured samples in the selected region.
      if (x(first) === low) { maximum = Math.max(maximum, y(first)); samples++; }
      if (i < count && x(i) === high) { maximum = Math.max(maximum, y(i)); samples++; }
      return samples ? maximum : null;
    }
    return integral;
  }
  async function renderPeak() {
    const low = Number($("peak-min").value), high = Number($("peak-max").value), metric = $("peak-metric").value, axis = $("peak-axis").value;
    const l = layout("peak"); l.margin = {l: 65, r: 28, t: 12, b: 40};
    l.xaxis.title.text = {time: "Experiment time / h", voltage: "Potential / V (nearest EC sample)", capacity: "Capacity / mAh (nearest EC sample)", index: "Acquisition number"}[axis];
    l.yaxis.title.text = metric === "integral" ? "Integral / a.u. × ppm" : "Maximum intensity / a.u.";
    const validBounds = finite(low) && finite(high) && high > low;
    ui.peakRows = validBounds ? ui.experiment.spectra.map((s, i) => {
      const t = representativeTime(s), ec = nearestEC(t);
      return {spectrum_id: s.id, label: s.label, source: s.source, acquisition_number: i + 1, time_s: t,
        ec_time_s: ec?.time_s ?? null, ec_sample_offset_s: ec?.delta_s ?? null,
        voltage_V: ec?.voltage_V ?? null, capacity_mAh: ec?.capacity_mAh ?? null,
        value: peakValue(s, low, high, metric), region_min_ppm: low, region_max_ppm: high,
        measurement: metric, alignment_method: ui.experiment.alignment?.method || "unaligned",
        timing_uncertainty_s: ui.experiment.alignment?.uncertainty_s ?? null};
    }) : [];
    const rows = ui.peakRows.map(r => ({...r, x: axis === "index" ? r.acquisition_number : axis === "time" ? finite(r.time_s) ? r.time_s / 3600 : null : axis === "voltage" ? r.voltage_V : r.capacity_mAh})).filter(r => finite(r.value) && finite(r.x));
    const trace = {type: "scatter", mode: "lines+markers", x: rows.map(r => r.x), y: rows.map(r => r.value),
      customdata: rows.map(r => r.spectrum_id), line: {color: "#8aa476", width: 1.3}, marker: {size: 5, color: rows.map(r => r.spectrum_id === ui.selectedId ? "#c58b63" : "#8aa476"), line: {color: "#fff", width: 1}},
      hovertemplate: "%{x:.5g}<br>%{y:.6g}<extra></extra>"};
    if (!rows.length) l.annotations = emptyAnnotation(!validBounds ? "Enter a chemical-shift region with minimum < maximum." : !isAligned() && axis !== "index" ? "Align acquisition timing or choose acquisition number." : "No spectra contain enough points in this region and axis range.");
    await Plotly.react("peak-plot", rows.length ? [trace] : [], l, config);
    $("peak-count").textContent = `${rows.length} / ${ui.experiment.spectra.length} acquisitions`;
    $("peak-caption").textContent = axis === "voltage" || axis === "capacity" ? "At acquisition midpoint where duration is known; nearest in-range EC sample. Sample offsets are exported." : "Original intensities; no normalization or baseline correction. Unknown acquisition duration uses its start time.";
  }
  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob), link = document.createElement("a"); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
  }
  async function switchMode(mode) {
    if (mode === "live") { ui.previewLive = true; ui.mode = "live"; renderState(); return; }
    ui.previewLive = false; ui.modeBusy = true;
    try { await api("/api/mode", jsonRequest("POST", {mode})); ui.mode = mode; ui.signature = ""; }
    catch (error) { toast(error.message, true); }
    finally { ui.modeBusy = false; await refresh(true); }
  }
  async function simulationAction(action) {
    try {
      await saveAnalysis(); await api(`/api/simulation/${action}`, jsonRequest("POST", {speed: Number($("speed-select").value)}));
      ui.signature = ""; await refresh(true);
      if (action === "prepare") toast("Replay prepared. Start to receive measurements and completed NMR spectra progressively.");
      if (action === "disconnect") toast("Replay paused after communication interruption. Existing data are preserved.");
    } catch (error) { toast(error.message, true); }
  }
  function openSettings() { $("settings-dialog").showModal(); }
  function resetForImport() { ui.selectedId = null; ui.selectedIds.clear(); ui.hoveredId = null; ui.locked = false; ui.signature = ""; }
  async function applyAlignment(body) {
    return withBusy("Applying time alignment…", async () => {
      await saveAnalysis(); await api("/api/alignment", jsonRequest("POST", body)); ui.timeRange = null; ui.experiment = null; await refresh(true);
      ui.timeRange = defaultTimeRange(); await setTimeRange();
      toast("Timing assumption applied; original timestamps remain preserved.");
    });
  }
  function bindControls() {
    document.querySelectorAll(".mode-button").forEach(b => b.addEventListener("click", () => switchMode(b.dataset.mode)));
    $("settings-button").addEventListener("click", openSettings); $("timing-chip").addEventListener("click", openSettings);
    $("notice-details").addEventListener("click", () => { openSettings(); $("alignment-details").open = true; });
    $("demo-button").addEventListener("click", () => withBusy("Opening synthetic example…", async () => {
      await api("/api/demo", {method: "POST"}); resetForImport(); $("settings-dialog").close(); await refresh(true);
    }));
    $("import-button").addEventListener("click", () => $("import-dialog").showModal());
    document.querySelectorAll(".dialog-close").forEach(b => b.addEventListener("click", () => b.closest("dialog").close()));
    document.querySelectorAll("dialog").forEach(dialog => dialog.addEventListener("click", event => {
      if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); }
    }));
    $("import-form").addEventListener("submit", event => {
      event.preventDefault(); const ec = $("ec-file").files[0], nmr = $("nmr-file").files[0];
      if (!ec && !nmr) return toast("Choose an electrochemical file and/or a Bruker ZIP.", true);
      const form = new FormData(); if (ec) form.append("ec_file", ec); if (nmr) form.append("nmr_file", nmr);
      withBusy("Interpreting experimental data…", async () => { await api("/api/import", {method: "POST", body: form}); $("import-dialog").close(); resetForImport(); await refresh(true); });
    });
    $("same-start-button").addEventListener("click", () => applyAlignment({method: "same_start"}));
    $("alignment-form").addEventListener("submit", event => {
      event.preventDefault(); const body = {method: "manual", offset_s: Number($("offset-input").value)};
      [["interval-input", "interval_s"], ["duration-input", "duration_s"], ["uncertainty-input", "uncertainty_s"]].forEach(([id, key]) => { if ($(id).value !== "") body[key] = Number($(id).value); });
      applyAlignment(body);
    });
    ["prepare", "start", "stop", "disconnect", "reconnect", "fail"].forEach(action => $(action + "-button").addEventListener("click", () => simulationAction(action)));
    $("pause-button").addEventListener("click", () => simulationAction(["paused", "disconnected"].includes(ui.state?.state) ? "resume" : "pause"));
    $("save-button").addEventListener("click", () => withBusy("Saving analysis…", async () => {
      await saveAnalysis(); const response = await request("/api/session"); if (!response.ok) throw new Error("Analysis could not be exported.");
      downloadBlob(await response.blob(), `${safeName(ui.experiment.name)}.ecnmr.json`);
    }));
    $("reopen-button").addEventListener("click", () => $("session-file").click());
    $("session-file").addEventListener("change", () => {
      const file = $("session-file").files[0]; if (!file) return; const form = new FormData(); form.append("file", file);
      withBusy("Reopening saved analysis…", async () => { await api("/api/session", {method: "POST", body: form}); ui.experiment = null; ui.signature = ""; await refresh(true); }); $("session-file").value = "";
    });
    $("series-view").addEventListener("change", async () => { ui.seriesView = $("series-view").value; renderInfo(); await renderSeries(); queueAnalysisSave(); });
    let gainFrame = null;
    $("gain-input").addEventListener("input", () => {
      ui.gain = Number($("gain-input").value); $("gain-value").textContent = `${ui.gain.toFixed(2)}×`;
      if (!gainFrame) gainFrame = requestAnimationFrame(async () => { gainFrame = null; await renderSeries(); queueAnalysisSave(); });
    });
    $("full-spectrum").addEventListener("click", async () => {
      const s = currentSpectrum() || ui.experiment.spectra[0]; if (!s) return;
      ui.ppmRange = [Math.max(s.ppm[0], s.ppm.at(-1)), Math.min(s.ppm[0], s.ppm.at(-1))]; ui.pointCache.clear();
      await Promise.all([renderSeries(), renderSpectra()]); queueAnalysisSave();
    });
    $("focus-spectrum").addEventListener("click", async () => { ui.ppmRange = [...ui.focusRange]; ui.pointCache.clear(); await Promise.all([renderSeries(), renderSpectra()]); queueAnalysisSave(); });
    $("time-window").addEventListener("change", async () => { ui.timeRange = defaultTimeRange(); await setTimeRange(); });
    $("ec-view").addEventListener("change", async () => { await renderEC(); queueAnalysisSave(); });
    $("unlock-button").addEventListener("click", () => { ui.locked = false; ui.hoveredId = null; updateHighlight(); queueAnalysisSave(); });
    $("spectrum-select").addEventListener("change", () => selectSpectrum($("spectrum-select").value));
    $("spectrum-slider").addEventListener("input", () => { const s = ui.experiment.spectra[Number($("spectrum-slider").value)]; if (s) selectSpectrum(s.id); });
    $("previous-spectrum").addEventListener("click", () => { const i = ui.experiment.spectra.indexOf(currentSpectrum()); if (i > 0) selectSpectrum(ui.experiment.spectra[i - 1].id); });
    $("next-spectrum").addEventListener("click", () => { const i = ui.experiment.spectra.indexOf(currentSpectrum()); if (i < ui.experiment.spectra.length - 1) selectSpectrum(ui.experiment.spectra[i + 1].id); });
    $("latest-button").addEventListener("click", () => { const s = ui.experiment.spectra.at(-1); if (s) selectSpectrum(s.id); });
    $("follow-latest").addEventListener("change", queueAnalysisSave);
    $("clear-overlays").addEventListener("click", async () => { ui.selectedIds = new Set(ui.selectedId ? [ui.selectedId] : []); renderList(); renderInfo(); await renderSpectra(); queueAnalysisSave(); });
    $("track-button").addEventListener("click", async () => { await renderPeak(); queueAnalysisSave(); });
    ["peak-min", "peak-max", "peak-metric", "peak-axis"].forEach(id => $(id).addEventListener("change", async () => { await renderPeak(); queueAnalysisSave(); }));
    $("peak-analysis").addEventListener("toggle", async () => { if ($("peak-analysis").open) { await renderPeak(); Plotly.Plots.resize($("peak-plot")); } });
    $("spectrum-info-button").addEventListener("click", () => {
      const s = currentSpectrum(); $("metadata-content").textContent = JSON.stringify({alignment: ui.experiment.alignment,
        spectrum: s ? {id: s.id, label: s.label, source: s.source, original_time_s: s.time_s, mapped_ec_time_s: timeOf(s), duration_s: s.duration_s, metadata: s.metadata} : null,
        electrochemistry: {source: ui.experiment.ec.source, start_time: ui.experiment.ec.start_time, metadata: ui.experiment.ec.metadata}, metadata: ui.experiment.metadata, warnings: ui.experiment.warnings}, null, 2); $("metadata-dialog").showModal();
    });
    [["export-ec", "ec-plot", "electrochemistry"], ["export-spectrum", "spectrum-plot", "nmr_spectra"]].forEach(([id, plot, name]) => $(id).addEventListener("click", () => {
      Plotly.downloadImage(plot, {format: "png", width: plot === "ec-plot" ? 650 : 1600, height: plot === "ec-plot" ? 1600 : 650, scale: 2, filename: name}).catch(e => toast(e.message, true));
    }));
    $("export-peaks").addEventListener("click", async () => {
      await renderPeak(); if (!ui.peakRows.length) return toast("No peak results are available for export.");
      const columns = Object.keys(ui.peakRows[0]), field = value => value == null ? "" : `"${String(value).replace(/"/g, '""')}"`;
      downloadBlob(new Blob([[columns.join(","), ...ui.peakRows.map(row => columns.map(key => field(row[key])).join(","))].join("\r\n")], {type: "text/csv;charset=utf-8"}), `${safeName(ui.experiment.name)}_peak_tracking.csv`);
    });
  }
  document.addEventListener("DOMContentLoaded", async () => {
    bindControls(); if (!window.Plotly) return toast("The local plotting library did not load. Check the application installation.", true);
    await refresh(true); setInterval(() => refresh(), 800);
  });
})();
