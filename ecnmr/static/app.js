/* One renderer is shared by imported experiments and progressively arriving replay data. */
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const colors = ["#157f77", "#c78364", "#8b7bb1", "#7b9f5e", "#5a90b5", "#c28baf", "#a5a15d", "#688b86"];
  const ui = {
    experiment: null, state: null, mode: "offline", selectedIds: new Set(), selectedId: null,
    seriesView: "list", signature: "", pollBusy: false, renderBusy: false, renderPending: false,
    peakRows: [], initialized: false, analysisTimer: null, toastTimer: null, lastError: "", modeBusy: false, previewLive: false,
  };
  window.ECNMR = {
    get experiment() { return ui.experiment; }, get state() { return ui.state; },
    get selectedIds() { return new Set(ui.selectedIds); }, get selectedId() { return ui.selectedId; },
    setSelection: (id, overlay = false) => selectSpectrum(id, overlay), refresh: () => refresh(true),
  };
  const config = {responsive: true, displaylogo: false, scrollZoom: true,
    modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "hoverCompareCartesian", "hoverClosestCartesian"]};
  const plotFont = {family: 'Inter, "Segoe UI", Arial, sans-serif', size: 10, color: "#7d8e77"};
  const baseAxis = {gridcolor: "#edf1e8", zerolinecolor: "#e0e7da", showline: false, ticks: "", tickfont: {size: 9}, title: {font: {size: 10}, standoff: 12}, automargin: true};
  const axis = () => structuredClone(baseAxis);
  const layout = (key) => ({font: {...plotFont}, paper_bgcolor: "#fff", plot_bgcolor: "#fff", showlegend: false,
    margin: {l: 58, r: 28, t: 15, b: 39}, hoverlabel: {font: {size: 10}, bgcolor: "#fff", bordercolor: "#dce7d4"},
    uirevision: `${ui.experiment?.id || "empty"}:${key}`, xaxis: axis(), yaxis: axis(),
    hovermode: "closest", dragmode: "zoom"});
  const finite = (v) => typeof v === "number" && Number.isFinite(v);
  const fmt = (n, digits = 2) => finite(n) ? Number(n).toLocaleString(undefined, {maximumFractionDigits: digits}) : "—";
  const nfmt = (n) => finite(n) ? Number(n).toLocaleString() : "—";
  const hours = (seconds) => finite(seconds) ? `${fmt(seconds / 3600, 3)} h` : "Timing unknown";
  const safeName = (str) => String(str || "experiment").replace(/[^a-zA-Z0-9_\-.]/g, "_").slice(0, 90);
  const basename = (str) => String(str || "").split(/[\\/]/).filter(Boolean).pop() || "Not loaded";
  const spectrumColor = (id) => colors[Math.max(0, ui.experiment?.spectra.findIndex(s => s.id === id) || 0) % colors.length];
  const currentSpectrum = () => ui.experiment?.spectra.find(s => s.id === ui.selectedId);
  const isAligned = () => ui.experiment && ui.experiment.alignment?.method !== "unaligned";
  const timeOf = (s) => isAligned() && finite(s.time_s) ? s.time_s + (ui.experiment.alignment.offset_s || 0) : null;
  const durationOf = (s) => finite(s.duration_s) && s.duration_s >= 0 ? s.duration_s : null;
  const representativeTime = (s) => finite(timeOf(s)) ? timeOf(s) + (durationOf(s) || 0) / 2 : null;
  const request = window.ECNMR_TRANSPORT || window.fetch.bind(window);

  async function api(path, options = {}) {
    const response = await request(path, options);
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try { const body = await response.json(); message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || body); } catch (_) { /* Preserve HTTP error. */ }
      throw new Error(message);
    }
    return response.status === 204 ? null : response.json();
  }
  const jsonRequest = (method, body) => ({method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  function toast(message, error = false) {
    $("toast").textContent = message; $("toast").classList.toggle("error", error); $("toast").hidden = false;
    clearTimeout(ui.toastTimer); ui.toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 10000 : 5500);
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
      const state = await api("/api/state");
      const nextSignature = signature(state);
      ui.state = state;
      if (!ui.modeBusy && !ui.previewLive) ui.mode = state.mode || ui.mode;
      if (force || nextSignature !== ui.signature || !ui.experiment) {
        const experiment = await api("/api/experiment");
        const fresh = !ui.experiment || ui.experiment.id !== experiment.id;
        const oldCount = ui.experiment?.spectra.length || 0;
        ui.experiment = experiment;
        ui.signature = nextSignature;
        if (fresh || force) {
          restoreAnalysis(experiment.analysis || {}, fresh);
          restoreAlignmentInputs(experiment);
        }
        const availableIds = new Set(experiment.spectra.map(s => s.id));
        ui.selectedIds = new Set([...ui.selectedIds].filter(id => availableIds.has(id)));
        if (!availableIds.has(ui.selectedId)) ui.selectedId = null;
        if (experiment.spectra.length && !ui.selectedId) {
          const first = experiment.spectra[0]; ui.selectedId = first.id; ui.selectedIds.add(first.id);
        }
        if (!fresh && experiment.spectra.length > oldCount && ui.mode === "simulation" && $("follow-latest").checked) {
          const newest = experiment.spectra.at(-1);
          if (ui.selectedIds.size <= 1) ui.selectedIds = new Set([newest.id]);
          else ui.selectedIds.add(newest.id);
          ui.selectedId = newest.id;
        }
        await render();
      }
      renderState();
      $("connection-label").textContent = window.ECNMR_TRANSPORT ? "Running in this browser" : "Service connected"; ui.lastError = "";
    } catch (error) {
      $("connection-label").textContent = "Service unavailable · retrying";
      if (error.message !== ui.lastError) toast(error.message, true);
      ui.lastError = error.message;
    } finally { ui.pollBusy = false; }
  }
  function restoreAnalysis(analysis, fresh) {
    if (Array.isArray(analysis.selected_ids)) ui.selectedIds = new Set(analysis.selected_ids);
    else if (fresh) ui.selectedIds.clear();
    if (analysis.selected_id) ui.selectedId = analysis.selected_id;
    else if (fresh) ui.selectedId = [...ui.selectedIds][0] || null;
    if (finite(analysis.peak_min)) $("peak-min").value = analysis.peak_min;
    if (finite(analysis.peak_max)) $("peak-max").value = analysis.peak_max;
    if (analysis.x_axis) $("peak-axis").value = analysis.x_axis;
    if (analysis.peak_metric) $("peak-metric").value = analysis.peak_metric;
    if (analysis.ec_view) $("ec-view").value = analysis.ec_view;
    if (typeof analysis.follow_latest === "boolean") $("follow-latest").checked = analysis.follow_latest;
    if (fresh && !finite(analysis.peak_min) && ui.experiment.spectra.length) {
      const spectrum = ui.experiment.spectra[0];
      let peak = 0;
      for (let i = 1; i < spectrum.intensity.length; i++) if (Math.abs(spectrum.intensity[i]) > Math.abs(spectrum.intensity[peak])) peak = i;
      const span = Math.abs(spectrum.ppm.at(-1) - spectrum.ppm[0]);
      const halfWidth = Math.max(span * 0.025, 0.1);
      $("peak-min").value = (spectrum.ppm[peak] - halfWidth).toFixed(3);
      $("peak-max").value = (spectrum.ppm[peak] + halfWidth).toFixed(3);
      if (!isAligned()) $("peak-axis").value = "index";
    }
  }
  function restoreAlignmentInputs(experiment) {
    const alignment = experiment.alignment || {};
    const durations = experiment.spectra.map(spectrum => spectrum.duration_s);
    const sharedDuration = durations.length && durations.every(value => finite(value) && value === durations[0]) ? durations[0] : null;
    $("offset-input").value = finite(alignment.offset_s) ? alignment.offset_s : 0;
    $("interval-input").value = finite(alignment.assumed_interval_s) ? alignment.assumed_interval_s : "";
    $("duration-input").value = finite(sharedDuration) ? sharedDuration : "";
    $("uncertainty-input").value = finite(alignment.uncertainty_s) ? alignment.uncertainty_s : "";
  }
  function analysis() {
    return {selected_ids: [...ui.selectedIds], selected_id: ui.selectedId,
      peak_min: Number($("peak-min").value), peak_max: Number($("peak-max").value),
      x_axis: $("peak-axis").value, peak_metric: $("peak-metric").value,
      ec_view: $("ec-view").value, follow_latest: $("follow-latest").checked};
  }
  function queueAnalysisSave() {
    clearTimeout(ui.analysisTimer);
    ui.analysisTimer = setTimeout(() => saveAnalysis().catch(e => toast(`Analysis settings could not be saved: ${e.message}`, true)), 350);
  }
  async function saveAnalysis() {
    clearTimeout(ui.analysisTimer);
    await api("/api/analysis", jsonRequest("PUT", analysis()));
  }
  function renderState() {
    const state = ui.state || {};
    document.querySelectorAll(".mode-button").forEach(button => {
      const active = button.dataset.mode === ui.mode;
      button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active));
    });
    $("mode-kicker").textContent = {offline: "OFFLINE ANALYSIS", simulation: "SIMULATED ACQUISITION", live: "LIVE ACQUISITION · UNVERIFIED"}[ui.mode] || "OFFLINE ANALYSIS";
    $("acquisition-panel").hidden = ui.mode === "offline";
    $("simulation-controls").hidden = ui.mode !== "simulation";
    $("live-notice").hidden = ui.mode !== "live";
    const label = ui.mode === "live" ? "Hardware disabled" : (state.state || "ready");
    $("run-state").textContent = label;
    $("acquisition-status").textContent = state.state || "ready";
    $("run-dot").className = `status-dot ${state.state || ""}`;
    const running = state.state === "running", paused = ["paused", "disconnected"].includes(state.state);
    $("start-button").disabled = state.state !== "ready";
    $("prepare-button").disabled = running;
    $("pause-button").disabled = !running && !paused;
    $("pause-button").textContent = paused ? "▶ Resume" : "Ⅱ Pause";
    $("stop-button").disabled = !running && !paused;
    $("disconnect-button").disabled = !running;
    $("reconnect-button").disabled = !["paused", "disconnected"].includes(state.state);
    $("fail-button").disabled = !running;
    $("speed-select").disabled = running || paused;
    if (ui.mode === "simulation") {
      $("metric-time").innerHTML = `${fmt((state.elapsed_s || 0) / 3600, 2)} <small>h</small>`;
      $("metric-time-detail").textContent = `${fmt(state.speed ?? Number($("speed-select").value), 0)}× replay · ${label}`;
    }
    $("event-label").textContent = state.event_count ? `${state.event_count} acquisition events logged` : "No hardware activated";
    if (state.error) {
      $("notice-banner").hidden = false;
      $("notice-text").textContent = `${state.error} Acquisition is interrupted; existing measurements are preserved.`;
      $("notice-details").hidden = true;
    }
  }
  async function render() {
    if (ui.renderBusy) { ui.renderPending = true; return; }
    if (!ui.experiment || !window.Plotly) return;
    ui.renderBusy = true;
    try {
      renderInfo(); renderList();
      await Promise.all([renderEC(), renderSpectra(), renderPeak(), ui.seriesView === "map" ? renderHeatmap() : Promise.resolve()]);
      if (!ui.initialized) { attachPlotEvents(); ui.initialized = true; }
    } finally {
      ui.renderBusy = false;
      if (ui.renderPending) { ui.renderPending = false; await render(); }
    }
  }
  function renderInfo() {
    const exp = ui.experiment, ec = exp.ec, spectra = exp.spectra;
    const synthetic = exp.metadata?.synthetic || exp.alignment?.method === "synthetic" || /synthetic/i.test(exp.name || "");
    $("experiment-title").textContent = exp.name || "EC–NMR experiment";
    $("experiment-subtitle").textContent = synthetic ? "Synthetic cycling experiment · known acquisition timing · local analysis" : "Experimental measurements · original units and acquisition metadata preserved";
    $("data-badge").textContent = synthetic ? "SYNTHETIC DATA" : "EXPERIMENTAL DATA";
    $("data-badge").classList.toggle("real", !synthetic);
    $("ec-source").textContent = basename(ec.source || ec.metadata?.source);
    $("ec-source").title = ec.source || "";
    $("nmr-source").textContent = spectra.length ? `${spectra.length} spectra · ${basename(spectra[0].source)}` : "No completed spectra yet";
    $("nmr-source").title = spectra[0]?.source || "";
    $("metric-ec").textContent = nfmt(ec.time_s.length);
    $("metric-spectra").textContent = nfmt(spectra.length);
    const nucleus = spectra[0]?.metadata?.nucleus || exp.metadata?.nmr?.nucleus || exp.metadata?.nucleus;
    $("metric-nucleus").textContent = nucleus ? `${nucleus} · ${nfmt(spectra[0]?.ppm.length)} points / spectrum` : `${nfmt(spectra[0]?.ppm.length)} points / spectrum`;
    const derivedCurrent = /derived|reconstructed/i.test(ec.metadata?.current_method || "");
    const signedCharge = /signed|Q-Qo/.test(`${ec.metadata?.capacity_method || ""} ${ec.metadata?.capacity_column || ""}`);
    $("metric-ec-detail").textContent = ec.time_s.length ? `Potential · ${derivedCurrent ? "derived current" : "current"}${ec.capacity_mAh?.some(finite) ? signedCharge ? " · signed charge" : " · capacity" : ""}` : "Waiting for EC measurements";
    $("ec-view").querySelector('[value="capacity"]').textContent = signedCharge ? "Signed charge & current" : "Capacity & current";
    $("peak-axis").querySelector('[value="capacity"]').textContent = signedCharge ? "Signed charge / mAh" : "Capacity / mAh";
    if (ui.mode !== "simulation") {
      const span = ec.time_s.length ? ec.time_s.at(-1) - ec.time_s[0] : null;
      $("metric-time").innerHTML = `${fmt(span === null ? null : span / 3600, 2)} <small>h</small>`;
      $("metric-time-detail").textContent = ec.start_time ? `EC start: ${ec.start_time}` : "Elapsed EC time · absolute start unknown";
    }
    const selected = currentSpectrum();
    const index = selected ? spectra.indexOf(selected) + 1 : null;
    $("metric-selected").textContent = selected ? `${String(index).padStart(2, "0")} / ${spectra.length}` : "—";
    $("metric-selection-time").textContent = selected ? finite(timeOf(selected)) ? `EC time ${hours(timeOf(selected))}${durationOf(selected) !== null ? ` · ${fmt(durationOf(selected), 1)} s duration` : " · duration unknown"}` : "Acquisition timing is unavailable" : "Waiting for a completed spectrum";
    const alignment = exp.alignment || {method: "unaligned"};
    const aligned = alignment.method !== "unaligned";
    $("alignment-status").textContent = {manual: "Manual", metadata: "Metadata", synthetic: "Known", unaligned: "Unaligned"}[alignment.method] || alignment.method;
    $("alignment-status").classList.toggle("warning", !aligned || alignment.method === "manual");
    $("alignment-summary").textContent = !aligned ? "No verified common timeline. Spectra are shown in acquisition order until you define their timing." : alignment.method === "manual" ? `Manual offset ${fmt(alignment.offset_s, 3)} s. ${finite(alignment.uncertainty_s) ? `Uncertainty ±${fmt(alignment.uncertainty_s)} s.` : "Timing uncertainty is unknown."} A supplied row cadence remains an assumption.` : alignment.method === "synthetic" ? "Known synthetic timing. Each acquisition interval is linked to the electrochemical timeline." : `Metadata alignment · offset ${fmt(alignment.offset_s, 3)} s. ${finite(alignment.uncertainty_s) ? `Uncertainty ±${fmt(alignment.uncertainty_s)} s.` : "Timing uncertainty is unknown."}`;
    const warnings = Array.isArray(exp.warnings) ? exp.warnings : [];
    const warningMessage = !aligned ? "The supplied NMR rows have no validated individual timestamps. Define a manual offset and assumed cadence before linking them to EC time." : alignment.method === "manual" ? "Manual time alignment is active. Row cadence and synchronization are user assumptions; interpret linked measurements with that uncertainty." : warnings.length ? warnings.slice(0, 2).join(" ") : "";
    $("notice-banner").hidden = !warningMessage;
    $("notice-text").textContent = warningMessage;
    $("notice-details").hidden = aligned && alignment.method !== "manual";
    $("series-caption").textContent = aligned ? "Acquisition intervals are linked to EC time." : "Acquisition order only · timing unavailable.";
    $("overlay-count").textContent = `${ui.selectedIds.size} selected`;
    $("spectrum-caption").textContent = selected ? `${selected.label || `Spectrum ${index}`} · chemical shift / ppm` : "Waiting for completed spectra";
    renderState();
  }
  function renderList() {
    const list = $("spectrum-list");
    const oldScroll = list.scrollTop;
    const fragment = document.createDocumentFragment();
    if (!ui.experiment.spectra.length) {
      const empty = document.createElement("div"); empty.className = "list-empty";
      empty.textContent = "Completed NMR spectra will appear here as acquisition progresses."; fragment.append(empty);
    }
    ui.experiment.spectra.forEach((s, index) => {
      const row = document.createElement("div"); row.className = `spectrum-row${s.id === ui.selectedId ? " selected" : ""}`;
      row.dataset.spectrumId = s.id; row.dataset.testid = "spectrum-row"; row.tabIndex = 0; row.setAttribute("role", "button");
      row.setAttribute("aria-label", `${s.label || `Spectrum ${index + 1}`}, ${hours(timeOf(s))}`);
      const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.checked = ui.selectedIds.has(s.id);
      checkbox.setAttribute("aria-label", `Overlay ${s.label || `spectrum ${index + 1}`}`); checkbox.dataset.testid = "overlay-checkbox";
      checkbox.addEventListener("click", event => { event.stopPropagation(); toggleOverlay(s.id); });
      const main = document.createElement("div"); main.className = "row-main";
      const title = document.createElement("strong"), color = document.createElement("i"); color.className = "row-color"; color.style.background = spectrumColor(s.id);
      title.dataset.testid = "spectrum-select";
      title.append(color, document.createTextNode(s.label || `Spectrum ${String(index + 1).padStart(2, "0")}`));
      const subtitle = document.createElement("small"); subtitle.textContent = `${nfmt(s.ppm.length)} points · ${s.metadata?.nucleus || "NMR"}`;
      main.append(title, subtitle);
      const time = document.createElement("div"); time.className = "row-time"; time.textContent = finite(timeOf(s)) ? hours(timeOf(s)) : `Row ${index + 1}`;
      const duration = document.createElement("span"); duration.textContent = durationOf(s) !== null ? `${fmt(durationOf(s), 1)} s` : "duration unknown"; time.append(duration);
      row.append(checkbox, main, time);
      row.addEventListener("click", event => selectSpectrum(s.id, event.ctrlKey || event.metaKey || event.shiftKey));
      row.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectSpectrum(s.id, event.shiftKey); } });
      fragment.append(row);
    });
    list.replaceChildren(fragment); list.scrollTop = oldScroll;
  }
  /* Keep extrema while thinning long lines, so a narrow experimental peak is not discarded. */
  function thin(x, y, limit = 3500) {
    if (x.length <= limit) return {x, y};
    const sx = [], sy = [], width = Math.ceil(x.length / (limit / 2));
    for (let i = 0; i < x.length; i += width) {
      let min = i, max = i;
      for (let j = i + 1; j < Math.min(i + width, x.length); j++) { if (y[j] < y[min]) min = j; if (y[j] > y[max]) max = j; }
      for (const j of min === max ? [min] : [min, max].sort((a, b) => a - b)) { sx.push(x[j]); sy.push(y[j]); }
    }
    return {x: sx, y: sy};
  }
  const emptyAnnotation = (text) => [{text, x: 0.5, y: 0.5, xref: "paper", yref: "paper", showarrow: false, font: {size: 10, color: "#9ba98f"}}];
  async function renderEC() {
    const ec = ui.experiment.ec, selected = currentSpectrum(), capacity = $("ec-view").value === "capacity";
    const derivedCurrent = /derived|reconstructed/i.test(ec.metadata?.current_method || "");
    const signedCharge = /signed|Q-Qo/.test(`${ec.metadata?.capacity_method || ""} ${ec.metadata?.capacity_column || ""}`);
    const chargeName = signedCharge ? "Signed charge" : "Capacity";
    const currentName = derivedCurrent ? "Derived interval-mean current" : "Current";
    const x = ec.time_s.map(t => t / 3600), y = capacity ? ec.capacity_mAh || [] : ec.voltage_V || [];
    const lines = [], potential = thin(x, y, 6500), current = thin(x, ec.current_mA || [], 4500);
    if (y.length && y.some(finite)) lines.push({type: "scatter", mode: "lines", ...potential, name: capacity ? chargeName : "Potential", line: {color: colors[0], width: 1.8}, hovertemplate: `%{x:.4f} h<br>${capacity ? chargeName : "Potential"}: %{y:.5g} ${capacity ? "mAh" : "V"}<extra></extra>`});
    if (ec.current_mA?.some(finite)) lines.push({type: "scatter", mode: "lines", ...current, name: currentName, yaxis: "y2", line: {color: "#d39b82", width: 1.05}, opacity: 0.8, hovertemplate: `%{x:.4f} h<br>${currentName}: %{y:.5g} mA<extra></extra>`});
    const l = layout("ec"); l.margin.r = 67; l.xaxis.title.text = "Experiment time / h"; l.yaxis.title.text = capacity ? `${chargeName} / mAh` : "Potential / V";
    l.yaxis.title.font.color = colors[0]; l.yaxis.tickfont.color = "#76958b";
    l.yaxis2 = {...axis(), overlaying: "y", side: "right", showgrid: false, zeroline: false,
      title: {text: derivedCurrent ? "Derived current / mA" : "Current / mA", font: {size: 10, color: "#bc947e"}, standoff: 12}, tickfont: {size: 9, color: "#b49c86"}};
    l.shapes = [];
    if (selected && finite(timeOf(selected))) {
      const start = timeOf(selected) / 3600, duration = durationOf(selected);
      if (duration !== null && duration > 0) l.shapes.push({type: "rect", xref: "x", yref: "paper", x0: start, x1: start + duration / 3600, y0: 0, y1: 1, fillcolor: "#157f7720", line: {width: 0}, layer: "below"});
      l.shapes.push({type: "line", xref: "x", yref: "paper", x0: start, x1: start, y0: 0, y1: 1, line: {color: "#74a995", width: 1, dash: "dot"}});
      if (ui.state?.state === "running") l.shapes.push({type: "line", xref: "x", yref: "paper", x0: ui.state.elapsed_s / 3600, x1: ui.state.elapsed_s / 3600, y0: 0, y1: 1, line: {color: "#c6d6bb", width: 1}});
    }
    if (!lines.length) l.annotations = emptyAnnotation("Electrochemical measurements will appear here.");
    $("ec-legend").textContent = capacity ? `${chargeName} / mAh` : "Potential / V";
    const currentLegend = $("ec-legend").parentElement.lastChild;
    if (currentLegend.nodeType === Node.TEXT_NODE) currentLegend.textContent = derivedCurrent ? "Derived current / mA" : "Current / mA";
    $("ec-legend").parentElement.title = [ec.metadata?.current_method, ec.metadata?.capacity_method || ec.metadata?.capacity_basis].filter(Boolean).join(". ");
    await Plotly.react("ec-plot", lines, l, config);
  }
  async function renderSpectra() {
    const selected = ui.experiment.spectra.filter(s => ui.selectedIds.has(s.id));
    const lines = selected.map(s => ({type: "scatter", mode: "lines", ...thin(s.ppm, s.intensity),
      name: s.label || s.id, line: {color: spectrumColor(s.id), width: s.id === ui.selectedId ? 1.6 : 1.1}, opacity: s.id === ui.selectedId ? 1 : 0.78,
      hovertemplate: `%{x:.4f} ppm<br>%{y:.5g}<extra>${escapeHTML(s.label || s.id)}</extra>`}));
    const l = layout("spectra"); l.xaxis.title.text = "Chemical shift / ppm"; l.xaxis.autorange = "reversed"; l.yaxis.title.text = "Intensity / a.u."; l.margin.r = 19; l.margin.l = 65;
    l.showlegend = selected.length > 1; l.legend = {orientation: "h", x: 0, y: 1.1, font: {size: 8}, itemsizing: "constant", tracegroupgap: 2};
    const low = Number($("peak-min").value), high = Number($("peak-max").value);
    if (Number.isFinite(low) && Number.isFinite(high) && high > low) l.shapes = [{type: "rect", xref: "x", yref: "paper", x0: low, x1: high, y0: 0, y1: 1, fillcolor: "#a3b8790d", line: {color: "#c0d0aa", width: 0.6, dash: "dot"}, layer: "below"}];
    if (!lines.length) l.annotations = emptyAnnotation(ui.experiment.spectra.length ? "Select spectra from the acquisition list." : "Waiting for a completed NMR acquisition.");
    await Plotly.react("spectrum-plot", lines, l, config);
  }
  async function renderHeatmap() {
    const spectra = ui.experiment.spectra, l = layout("map");
    l.margin = {l: 52, r: 18, t: 5, b: 35}; l.xaxis.title.text = "Chemical shift / ppm"; l.xaxis.autorange = "reversed";
    const timed = spectra.length && spectra.every(s => finite(timeOf(s)));
    l.yaxis.title.text = timed ? "EC time / h" : "Acquisition number";
    if (!spectra.length) { l.annotations = emptyAnnotation("No completed spectra yet."); return Plotly.react("heatmap-plot", [], l, config); }
    const count = spectra[0].ppm.length, step = Math.max(1, Math.ceil(count / 300));
    const indices = Array.from({length: Math.ceil(count / step)}, (_, i) => i * step);
    const x = indices.map(i => spectra[0].ppm[i]);
    const sameAxis = spectra.every(s => s.ppm.length === count && s.ppm[0] === spectra[0].ppm[0] && s.ppm.at(-1) === spectra[0].ppm.at(-1));
    if (!sameAxis) { l.annotations = emptyAnnotation("Intensity map requires a shared chemical-shift axis."); return Plotly.react("heatmap-plot", [], l, config); }
    const z = spectra.map(s => indices.map(i => {
      let value = s.intensity[i];
      for (let j = i + 1; j < Math.min(i + step, count); j++) if (Math.abs(s.intensity[j]) > Math.abs(value)) value = s.intensity[j];
      return value;
    }));
    const y = spectra.map((s, i) => timed ? timeOf(s) / 3600 : i + 1);
    const trace = {type: "heatmap", x, y, z, colorscale: [[0, "#fafbf4"], [0.18, "#e1efdc"], [0.48, "#a3cbb3"], [0.75, "#4e9a8b"], [1, "#186f69"]], showscale: false,
      hovertemplate: `%{x:.3f} ppm<br>${timed ? "EC time" : "Acquisition"}: %{y:.4g}<br>Intensity: %{z:.5g}<extra></extra>`};
    l.yaxis.autorange = "reversed";
    if (ui.selectedId) {
      const index = spectra.findIndex(s => s.id === ui.selectedId), selectedY = y[index];
      if (finite(selectedY)) l.shapes = [{type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: selectedY, y1: selectedY, line: {color: "#b47c4f", width: 1, dash: "dot"}}];
    }
    await Plotly.react("heatmap-plot", [trace], l, config);
    const plot = $("heatmap-plot");
    if (!plot.dataset.linked) {
      plot.on("plotly_click", event => {
        const point = event.points?.[0]; if (!point) return;
        const rowIndex = Array.isArray(point.pointNumber) ? point.pointNumber[0] : y.findIndex(v => v === point.y);
        const spectrum = ui.experiment.spectra[rowIndex]; if (spectrum) selectSpectrum(spectrum.id);
      }); plot.dataset.linked = "true";
    }
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
  function attachPlotEvents() {
    $("ec-plot").on("plotly_click", async event => {
      const point = event.points?.[0]; if (!point || !finite(point.x)) return;
      try {
        const result = await api(`/api/spectrum-match?time_s=${encodeURIComponent(point.x * 3600)}`);
        if (result.spectrum_id) {
          await selectSpectrum(result.spectrum_id);
          $("match-description").textContent = result.distance_s === 0 ? "Selected time falls within this NMR acquisition." : `Nearest valid acquisition · ${fmt(result.distance_s, 2)} s from selected EC time.`;
        } else {
          $("match-description").textContent = result.reason || "No acquisition can be linked at this time.";
          toast(result.reason || "Define acquisition timing before linking the curves.");
        }
      } catch (error) { toast(error.message, true); }
    });
    $("peak-plot").on("plotly_click", event => { const id = event.points?.[0]?.customdata; if (id) selectSpectrum(id); });
  }
  async function selectSpectrum(id, overlay = false) {
    const s = ui.experiment?.spectra.find(spectrum => spectrum.id === id); if (!s) return;
    ui.selectedId = id;
    if (overlay) ui.selectedIds.add(id); else ui.selectedIds = new Set([id]);
    if (ui.mode === "simulation" && ui.state?.state === "running") $("follow-latest").checked = false;
    const time = timeOf(s), duration = durationOf(s);
    $("match-description").textContent = finite(time) ? duration !== null ? `NMR interval: ${hours(time)} – ${hours(time + duration)}.` : `NMR start: ${hours(time)} · duration unknown.` : "This acquisition has no validated EC timestamp.";
    await render(); queueAnalysisSave();
  }
  async function toggleOverlay(id) {
    if (ui.selectedIds.has(id)) {
      ui.selectedIds.delete(id);
      if (ui.selectedId === id) ui.selectedId = [...ui.selectedIds].at(-1) || null;
    } else { ui.selectedIds.add(id); ui.selectedId = id; }
    if (ui.state?.state === "running") $("follow-latest").checked = false;
    await render(); queueAnalysisSave();
  }
  function escapeHTML(str) { return String(str).replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char])); }
  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob), link = document.createElement("a"); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
  }
  async function switchMode(mode) {
    if (mode === "live") { ui.previewLive = true; ui.mode = "live"; renderState(); return; }
    ui.previewLive = false;
    ui.modeBusy = true;
    try {
      await api("/api/mode", jsonRequest("POST", {mode})); ui.mode = mode; ui.signature = "";
    } catch (error) { toast(error.message, true); }
    finally { ui.modeBusy = false; await refresh(true); }
  }
  async function simulationAction(action) {
    try {
      await saveAnalysis();
      await api(`/api/simulation/${action}`, jsonRequest("POST", {speed: Number($("speed-select").value)}));
      ui.signature = ""; await refresh(true);
      if (action === "prepare") toast("Replay prepared. Start to receive EC measurements and completed NMR spectra progressively.");
      if (action === "disconnect") toast("Communication interrupted. Replay time is paused and existing data are preserved.");
      if (action === "reconnect") toast("Communication restored. Replay resumed.");
    } catch (error) { toast(error.message, true); }
  }
  function bindControls() {
    document.querySelectorAll(".mode-button").forEach(button => button.addEventListener("click", () => switchMode(button.dataset.mode)));
    $("demo-button").addEventListener("click", () => withBusy("Opening synthetic example…", async () => { await api("/api/demo", {method: "POST"}); ui.selectedId = null; ui.selectedIds.clear(); ui.signature = ""; await refresh(true); }));
    $("import-button").addEventListener("click", () => $("import-dialog").showModal());
    document.querySelectorAll(".dialog-close").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
    document.querySelectorAll("dialog").forEach(dialog => dialog.addEventListener("click", event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); } }));
    $("import-form").addEventListener("submit", event => {
      event.preventDefault();
      const ec = $("ec-file").files[0], nmr = $("nmr-file").files[0];
      if (!ec && !nmr) return toast("Choose at least one electrochemical or NMR dataset.", true);
      const form = new FormData(); if (ec) form.append("ec_file", ec); if (nmr) form.append("nmr_file", nmr);
      withBusy("Interpreting experimental data…", async () => {
        await api("/api/import", {method: "POST", body: form});
        $("import-dialog").close(); ui.selectedId = null; ui.selectedIds.clear(); ui.signature = "";
        await refresh(true); toast("Experimental data imported. Inspect the timing status before linking measurements.");
      });
    });
    $("alignment-form").addEventListener("submit", event => {
      event.preventDefault(); const body = {method: "manual", offset_s: Number($("offset-input").value)};
      [["interval-input", "interval_s"], ["duration-input", "duration_s"], ["uncertainty-input", "uncertainty_s"]].forEach(([id, key]) => { if ($(id).value !== "") body[key] = Number($(id).value); });
      withBusy("Applying manual time alignment…", async () => {
        await saveAnalysis(); await api("/api/alignment", jsonRequest("POST", body)); await refresh(true);
        toast("Manual alignment applied. The original timing metadata remain preserved.");
      });
    });
    $("notice-details").addEventListener("click", () => { $("alignment-details").open = true; $("offset-input").focus(); });
    ["prepare", "start", "stop", "disconnect", "reconnect", "fail"].forEach(action => $(action + "-button").addEventListener("click", () => simulationAction(action)));
    $("pause-button").addEventListener("click", () => simulationAction(["paused", "disconnected"].includes(ui.state?.state) ? "resume" : "pause"));
    $("save-button").addEventListener("click", () => withBusy("Saving the complete analysis…", async () => {
      await saveAnalysis(); const response = await request("/api/session"); if (!response.ok) throw new Error("The analysis could not be exported.");
      downloadBlob(await response.blob(), `${safeName(ui.experiment.name)}.ecnmr.json`); toast("Analysis saved with data, provenance, alignment and selections.");
    }));
    $("reopen-button").addEventListener("click", () => $("session-file").click());
    $("session-file").addEventListener("change", () => {
      const file = $("session-file").files[0]; if (!file) return;
      const form = new FormData(); form.append("file", file);
      withBusy("Reopening saved analysis…", async () => { await api("/api/session", {method: "POST", body: form}); ui.experiment = null; ui.signature = ""; await refresh(true); toast("Saved experiment and analysis settings reopened."); });
      $("session-file").value = "";
    });
    $("latest-button").addEventListener("click", () => { const latest = ui.experiment?.spectra.at(-1); if (latest) selectSpectrum(latest.id); });
    $("follow-latest").addEventListener("change", queueAnalysisSave);
    $("clear-overlays").addEventListener("click", async () => { ui.selectedIds = new Set(ui.selectedId ? [ui.selectedId] : []); await render(); queueAnalysisSave(); });
    $("ec-view").addEventListener("change", async () => { await renderEC(); queueAnalysisSave(); });
    $("track-button").addEventListener("click", async () => { await Promise.all([renderPeak(), renderSpectra()]); queueAnalysisSave(); });
    ["peak-min", "peak-max", "peak-metric", "peak-axis"].forEach(id => $(id).addEventListener("change", async () => { await Promise.all([renderPeak(), renderSpectra()]); queueAnalysisSave(); }));
    document.querySelectorAll("[data-series-view]").forEach(button => button.addEventListener("click", async () => {
      ui.seriesView = button.dataset.seriesView;
      document.querySelectorAll("[data-series-view]").forEach(tab => { const active = tab === button; tab.classList.toggle("active", active); tab.setAttribute("aria-selected", String(active)); });
      $("spectrum-list").hidden = ui.seriesView !== "list"; $("heatmap-plot").hidden = ui.seriesView !== "map";
      if (ui.seriesView === "map") await renderHeatmap();
    }));
    $("spectrum-info-button").addEventListener("click", () => {
      const s = currentSpectrum();
      $("metadata-content").textContent = JSON.stringify({experiment: ui.experiment.name, alignment: ui.experiment.alignment,
        spectrum: s ? {id: s.id, label: s.label, source: s.source, original_time_s: s.time_s, mapped_ec_time_s: timeOf(s), duration_s: s.duration_s, metadata: s.metadata} : null,
        electrochemistry: {source: ui.experiment.ec.source, start_time: ui.experiment.ec.start_time, metadata: ui.experiment.ec.metadata}, warnings: ui.experiment.warnings, metadata: ui.experiment.metadata}, null, 2);
      $("metadata-dialog").showModal();
    });
    [["export-ec", "ec-plot", "electrochemistry"], ["export-spectrum", "spectrum-plot", "nmr_spectra"]].forEach(([id, plot, name]) => $(id).addEventListener("click", () => {
      Plotly.downloadImage(plot, {format: "png", width: 1600, height: 650, scale: 2, filename: name}).catch(error => toast(error.message, true));
    }));
    $("export-peaks").addEventListener("click", () => {
      if (!ui.peakRows.length) return toast("No peak results are available for export.");
      const columns = Object.keys(ui.peakRows[0]);
      const csvField = value => value === null || value === undefined ? "" : `"${String(value).replace(/"/g, '""')}"`;
      const csv = [columns.join(","), ...ui.peakRows.map(row => columns.map(key => csvField(row[key])).join(","))].join("\r\n");
      downloadBlob(new Blob([csv], {type: "text/csv;charset=utf-8"}), `${safeName(ui.experiment.name)}_peak_tracking.csv`);
    });
  }
  document.addEventListener("DOMContentLoaded", async () => {
    bindControls();
    if (!window.Plotly) { toast("The local plotting library did not load. Restart the application after installing its dependencies.", true); return; }
    await refresh(true); setInterval(() => refresh(), 800);
  });
})();
