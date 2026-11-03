/* Browser-only transport for the shared EC–NMR interface. No device or network API. */
"use strict";
(() => {
  const clone = value => structuredClone(value);
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const fields = ["time_s", "voltage_V", "current_mA", "capacity_mAh"];
  let payload, source, mode = "offline", state = "ready", elapsed = 0, speed = 600;
  let error = null, revision = 0, eventCount = 0, last = performance.now(), pristineHTML = "";

  async function decodePayload() {
    const bytes = Uint8Array.from(atob(document.getElementById("ecnmr-payload").textContent.trim()), c => c.charCodeAt(0));
    if (!window.DecompressionStream) throw new Error("Use a current Chrome, Edge, Firefox or Safari browser to open this HTML.");
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    payload = JSON.parse(await new Response(stream).text());
    source = clone(payload.real || payload.demo);
    validate(source);
    restoreSettings();
  }
  const ready = decodePayload();
  function event() { revision++; eventCount++; }
  function endTime() {
    const ecEnd = source.ec.time_s.at(-1) || 0;
    const nmrEnd = source.spectra.reduce((end, s) => Math.max(end, finite(s.time_s) ? s.time_s + source.alignment.offset_s + (s.duration_s || 0) : 0), 0);
    return Math.max(ecEnd, nmrEnd);
  }
  function tick() {
    const now = performance.now();
    if (state === "running") {
      elapsed = Math.min(endTime(), elapsed + Math.max(0, now - last) / 1000 * speed);
      if (elapsed >= endTime()) { state = "completed"; event(); }
    }
    last = now;
  }
  function ecCount() {
    if (mode === "offline") return source.ec.time_s.length;
    const t = source.ec.time_s;
    let lo = 0, hi = t.length;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (t[mid] <= elapsed) lo = mid + 1; else hi = mid; }
    return lo;
  }
  function visibleSpectra() {
    return mode === "offline" ? source.spectra : source.spectra.filter(s => finite(s.time_s) && s.time_s + source.alignment.offset_s + (s.duration_s || 0) <= elapsed);
  }
  function status() {
    return {mode, state, elapsed_s: elapsed, speed, error, revision, event_count: eventCount,
      available_ec: ecCount(), available_spectra: visibleSpectra().length,
      total_ec: source.ec.time_s.length, total_spectra: source.spectra.length, hardware_validated: false};
  }
  function view() {
    const count = ecCount();
    const ec = {...source.ec, metadata: {...source.ec.metadata}};
    fields.forEach(key => { ec[key] = source.ec[key].slice(0, count); });
    if (ec.metadata.additional_columns) {
      ec.metadata.additional_columns = Object.fromEntries(Object.entries(ec.metadata.additional_columns).map(([key, values]) =>
        [key, Array.isArray(values) && values.length === source.ec.time_s.length ? values.slice(0, count) : values]));
    }
    return {...source, ec, spectra: visibleSpectra()};
  }
  function validate(exp) {
    if (!exp || exp.schema_version !== 1 || !Array.isArray(exp.spectra) || !exp.ec || !exp.alignment || !exp.metadata || !exp.analysis)
      throw new Error("This file is not a supported EC–NMR analysis session.");
    const n = exp.ec.time_s?.length;
    if (!Number.isInteger(n) || fields.some(key => !Array.isArray(exp.ec[key]) || exp.ec[key].length !== n))
      throw new Error("EC measurement arrays have inconsistent lengths.");
    if (exp.ec.time_s.some((t, i, times) => !finite(t) || i > 0 && t < times[i - 1]))
      throw new Error("EC times must be finite and nondecreasing.");
    if (fields.slice(1).some(key => exp.ec[key].some(v => v !== null && !finite(v))))
      throw new Error("EC values must be finite or explicitly unavailable.");
    if (!finite(exp.alignment.offset_s) || !["unaligned", "manual", "synthetic", "metadata"].includes(exp.alignment.method) ||
        exp.alignment.uncertainty_s != null && (!finite(exp.alignment.uncertainty_s) || exp.alignment.uncertainty_s < 0))
      throw new Error("Invalid alignment settings.");
    const ids = new Set();
    for (const s of exp.spectra) {
      if (!s.id || ids.has(s.id) || !Array.isArray(s.ppm) || !Array.isArray(s.intensity) || s.ppm.length < 2 || s.ppm.length !== s.intensity.length)
        throw new Error("Invalid spectrum identity or dimensions.");
      ids.add(s.id);
      const direction = Math.sign(s.ppm[1] - s.ppm[0]);
      if (!direction || s.ppm.some((v, i) => !finite(v) || i > 0 && Math.sign(v - s.ppm[i - 1]) !== direction) || s.intensity.some(v => !finite(v)))
        throw new Error("Spectral values must be finite and the ppm axis must be monotonic.");
      if (s.time_s != null && !finite(s.time_s) || s.duration_s != null && (!finite(s.duration_s) || s.duration_s < 0))
        throw new Error("Invalid spectrum acquisition interval.");
    }
    return exp;
  }
  function replace(exp) {
    if (state === "running") throw new Error("Stop or pause playback before replacing its data.");
    source = validate(clone(exp)); mode = "offline"; state = "ready"; elapsed = 0; error = null; event();
  }
  function saveSettings() {
    try {
      localStorage.setItem("ecnmr-html:" + source.id, JSON.stringify({analysis: source.analysis,
        alignment: source.alignment, intervals: source.spectra.map(s => ({time_s: s.time_s, duration_s: s.duration_s,
          timing_basis: s.metadata?.timing_basis, duration_basis: s.metadata?.duration_basis}))}));
    } catch (_) { /* File browsers may disable storage; downloaded sessions remain available. */ }
  }
  function restoreSettings() {
    try {
      const saved = JSON.parse(localStorage.getItem("ecnmr-html:" + source.id));
      if (!saved) return;
      const proposed = clone(source);
      proposed.analysis = saved.analysis;
      proposed.alignment = saved.alignment;
      if (saved.intervals.length !== proposed.spectra.length) return;
      saved.intervals.forEach((interval, i) => {
        proposed.spectra[i].time_s = interval.time_s;
        proposed.spectra[i].duration_s = interval.duration_s;
        if (interval.timing_basis) proposed.spectra[i].metadata.timing_basis = interval.timing_basis;
        if (interval.duration_basis) proposed.spectra[i].metadata.duration_basis = interval.duration_basis;
      });
      source = validate(proposed);
    } catch (_) { /* An invalid/stale browser preference cannot alter embedded source data. */ }
  }
  function manualAlign(body) {
    const proposed = clone(source);
    if (body.method !== "manual" || !finite(body.offset_s)) throw new Error("Supply a finite manual offset in seconds.");
    for (const key of ["interval_s", "duration_s", "uncertainty_s"]) {
      if (body[key] != null && (!finite(body[key]) || body[key] < 0 || key === "interval_s" && body[key] === 0))
        throw new Error("Cadence must be positive; duration and uncertainty must be nonnegative.");
    }
    proposed.spectra.forEach((s, i) => {
      if (body.interval_s != null) { s.time_s = i * body.interval_s; s.metadata.timing_basis = "operator-assumed uniform cadence"; }
      if (body.duration_s != null) { s.duration_s = body.duration_s; s.metadata.duration_basis = "operator supplied"; }
    });
    proposed.alignment = {method: "manual", offset_s: body.offset_s, uncertainty_s: body.uncertainty_s ?? null,
      assumed_interval_s: body.interval_s ?? null};
    replace(proposed); saveSettings();
  }
  function match(time) {
    const empty = {spectrum_id: null, distance_s: null, interval_start_s: null, interval_end_s: null, reason: "Time alignment is required"};
    if (!finite(time)) throw new Error("Selection time must be finite.");
    if (source.alignment.method === "unaligned") return empty;
    const candidates = visibleSpectra().filter(s => finite(s.time_s)).map(s => {
      const start = s.time_s + source.alignment.offset_s, end = start + (s.duration_s || 0);
      return {s, start, end, distance: Math.max(start - time, time - end, 0)};
    });
    if (!candidates.length) return empty;
    if (time < Math.min(...candidates.map(c => c.start)) || time > Math.max(...candidates.map(c => c.end)))
      return {...empty, reason: "Outside the available NMR acquisition range"};
    candidates.sort((a, b) => a.distance - b.distance || Math.abs(time - a.start) - Math.abs(time - b.start) || a.s.id.localeCompare(b.s.id));
    const c = candidates[0];
    return {spectrum_id: c.s.id, distance_s: c.distance, interval_start_s: c.start, interval_end_s: c.end,
      reason: c.distance === 0 ? "inside acquisition interval" : "nearest spectrum; outside acquisition interval"};
  }
  function simulation(action, body) {
    if (body.speed != null) {
      if (!finite(body.speed) || body.speed <= 0 || body.speed > 100000) throw new Error("Invalid playback speed.");
      speed = body.speed;
    }
    if (["prepare", "reset"].includes(action)) {
      if (state === "running") throw new Error("Stop playback before resetting.");
      if (source.alignment.method === "unaligned" || source.spectra.some(s => !finite(s.time_s)))
        throw new Error("Align the recording first, or load the synthetic example.");
      mode = "simulation"; state = "ready"; elapsed = 0; error = null;
    } else if (action === "start") {
      if (mode !== "simulation" || state !== "ready" || source.alignment.method === "unaligned" || source.spectra.some(s => !finite(s.time_s)))
        throw new Error("Prepare an aligned simulation before starting.");
      state = "running";
    } else if (["pause", "disconnect"].includes(action)) {
      if (state !== "running") throw new Error("Only running playback can pause.");
      state = "paused"; error = action === "disconnect" ? "Simulated communication loss; playback clock frozen, existing data preserved." : null;
    } else if (["resume", "reconnect"].includes(action)) {
      if (state !== "paused") throw new Error("Only paused playback can resume.");
      state = "running"; error = null;
    } else if (action === "stop") state = "stopped";
    else if (action === "fail") { state = "error"; error = "Simulated acquisition failure; existing measurements preserved."; }
    else throw new Error("Unknown simulation action.");
    last = performance.now(); event(); return status();
  }
  window.ECNMR_TRANSPORT = async (path, options = {}) => {
    try {
      await ready; tick();
      const url = new URL(path, "https://browser.local");
      const method = options.method || "GET";
      const body = typeof options.body === "string" ? JSON.parse(options.body) : {};
      let value;
      if (url.pathname === "/api/state") value = status();
      else if (url.pathname === "/api/experiment") value = view();
      else if (url.pathname === "/api/analysis" && method === "PUT") { source.analysis = body; saveSettings(); event(); value = body; }
      else if (url.pathname === "/api/session" && method === "GET") value = {...view(), metadata: {...source.metadata, capture_state: status(), standalone_html: true}};
      else if (url.pathname === "/api/session" && method === "POST") {
        const file = options.body.get("file");
        if (!file || file.size > 128 * 1024 * 1024) throw new Error("Choose a session JSON smaller than 128 MiB.");
        replace(JSON.parse(await file.text())); value = view();
      } else if (url.pathname === "/api/demo") { replace(payload.demo); restoreSettings(); value = view(); }
      else if (url.pathname === "/api/builtin-real") {
        if (!payload.real) throw new Error("This HTML contains only a synthetic example.");
        replace(payload.real); restoreSettings(); value = view();
      } else if (url.pathname === "/api/alignment") { manualAlign(body); value = view(); }
      else if (url.pathname === "/api/spectrum-match") value = match(Number(url.searchParams.get("time_s")));
      else if (url.pathname === "/api/mode") {
        if (!["offline", "simulation"].includes(body.mode)) throw new Error("Hardware acquisition is disabled in this HTML version.");
        if (state === "running") throw new Error("Stop or pause playback before changing modes.");
        // Unaligned real data are never assigned invented row timing for playback.
        if (body.mode === "simulation" && (source.alignment.method === "unaligned" || source.spectra.some(s => !finite(s.time_s)))) replace(payload.demo);
        mode = body.mode; state = "ready"; elapsed = 0; error = null; event(); value = status();
      } else if (url.pathname.startsWith("/api/simulation/")) value = simulation(url.pathname.split("/").at(-1), body);
      else throw new Error("Raw-file import needs the Python application. This HTML can reopen saved JSON sessions.");
      return new Response(JSON.stringify(value), {status: 200, headers: {"Content-Type": "application/json"}});
    } catch (e) {
      return new Response(JSON.stringify({detail: e.message}), {status: 400, headers: {"Content-Type": "application/json"}});
    }
  };
  document.addEventListener("DOMContentLoaded", async () => {
    pristineHTML = "<!DOCTYPE html>\n" + document.documentElement.outerHTML;
    const $ = id => document.getElementById(id);
    $("import-button").textContent = "Open JSON";
    $("import-button").addEventListener("click", event => { event.stopImmediatePropagation(); $("session-file").click(); }, true);
    $("download-html").addEventListener("click", () => {
      const link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([pristineHTML], {type: "text/html;charset=utf-8"}));
      link.download = "operando-ecnmr.html"; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 30000);
    });
    $("real-button").addEventListener("click", async () => {
      const response = await window.ECNMR_TRANSPORT("/api/builtin-real", {method: "POST"});
      if (response.ok) await window.ECNMR.refresh();
      else alert((await response.json()).detail);
    });
    try { await ready; $("real-button").hidden = !payload.real; }
    catch (e) { $("standalone-help").textContent = e.message; }
  });
})();
