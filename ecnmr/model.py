"""Shared representation and explicit timeline alignment. All times are seconds."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import math
import uuid
import numpy as np


def experiment(ec=None, spectra=None, metadata=None, warnings=None):
    return {
        "schema_version": 1, "id": str(uuid.uuid4()), "name": "Imported experiment",
        "ec": ec or {"time_s": [], "voltage_V": [], "current_mA": [],
                     "capacity_mAh": [], "source": None, "start_time": None, "metadata": {}},
        "spectra": spectra or [], "metadata": metadata or {}, "warnings": warnings or [],
        "alignment": {"method": "unaligned", "offset_s": 0, "uncertainty_s": None},
        "analysis": {"selected_ids": [], "peak_min": -5, "peak_max": 5, "x_axis": "time"},
    }


def _validate(exp):
    """Validate normalized scientific values and the saved-analysis envelope."""
    if exp.get("schema_version") != 1:
        raise ValueError("Unsupported session schema_version (expected 1)")
    if not isinstance(exp["id"], str) or not isinstance(exp["name"], str):
        raise ValueError("Session identifier and name must be text")
    if not isinstance(exp["metadata"], dict) or not isinstance(exp["analysis"], dict) or not isinstance(exp["warnings"], list):
        raise ValueError("Session metadata/analysis must be objects and warnings must be a list")
    ec = exp["ec"]
    if any(not isinstance(x, (int, float)) for x in ec["time_s"]):
        raise ValueError("EC times must be numbers in seconds")
    t = np.asarray(ec["time_s"], dtype=float)
    if t.ndim != 1 or not np.isfinite(t).all() or (np.diff(t) < 0).any():
        raise ValueError("EC times must be finite and nondecreasing")
    for key in ("voltage_V", "current_mA", "capacity_mAh"):
        if len(ec[key]) != len(t):
            raise ValueError(f"EC {key} must have one value per time point (null allowed)")
        if any(x is not None and (not isinstance(x, (int, float)) or not math.isfinite(x)) for x in ec[key]):
            raise ValueError(f"EC {key} contains a nonfinite value")
    ids = set()
    for s in exp["spectra"]:
        if s["id"] in ids:
            raise ValueError("Spectrum IDs must be unique")
        ids.add(s["id"])
        if len(s["ppm"]) != len(s["intensity"]) or len(s["ppm"]) < 2:
            raise ValueError("Spectrum axis and intensity lengths must match")
        if not np.isfinite(s["ppm"]).all() or not np.isfinite(s["intensity"]).all():
            raise ValueError("Spectrum contains nonfinite values")
        delta = np.diff(s["ppm"])
        if not ((delta > 0).all() or (delta < 0).all()):
            raise ValueError("Chemical shift axis must be strictly monotonic")
        if s.get("duration_s") is not None and (not math.isfinite(s["duration_s"]) or s["duration_s"] < 0):
            raise ValueError("Acquisition duration must be finite and nonnegative")
        if s.get("time_s") is not None and not math.isfinite(s["time_s"]):
            raise ValueError("Spectrum acquisition time must be finite or null")
    alignment = exp["alignment"]
    if alignment["method"] not in {"unaligned", "manual", "metadata", "synthetic"}:
        raise ValueError("Unknown alignment method")
    if not isinstance(alignment["offset_s"], (int, float)) or not math.isfinite(alignment["offset_s"]):
        raise ValueError("Alignment offset must be finite")
    u = alignment.get("uncertainty_s")
    if u is not None and (not math.isfinite(u) or u < 0):
        raise ValueError("Timing uncertainty must be finite and nonnegative")
    # Metadata and analysis are also persisted as JSON. Reject NaN anywhere,
    # including JSON's permissive nonstandard NaN/Infinity tokens.
    json.dumps(exp, allow_nan=False)
    return exp


def validate(exp):
    """Reject malformed sessions with an actionable error rather than a traceback."""
    try:
        return _validate(exp)
    except (AttributeError, KeyError, TypeError, OverflowError) as exc:
        raise ValueError(f"Invalid session structure: {exc}") from exc


def align(exp, *, offset_s=0, interval_s=None, duration_s=None, uncertainty_s=None, method="manual"):
    if method != "manual":
        raise ValueError("Imported data require explicit manual alignment; metadata clocks are unverified")
    result = deepcopy(exp)
    if interval_s is not None:
        if not math.isfinite(interval_s) or interval_s <= 0:
            raise ValueError("Assumed repetition interval must be positive")
        for i, spectrum in enumerate(result["spectra"]):
            spectrum["metadata"].setdefault("original_time_s", spectrum.get("time_s"))
            spectrum["time_s"] = i * interval_s
            spectrum["metadata"]["timing_basis"] = "operator-assumed uniform cadence"
    if duration_s is not None:
        for spectrum in result["spectra"]:
            spectrum["metadata"].setdefault("original_duration_s", spectrum.get("duration_s"))
            spectrum["duration_s"] = duration_s
            spectrum["metadata"]["duration_basis"] = "operator supplied"
    result["alignment"] = {"method": method, "offset_s": float(offset_s),
                           "uncertainty_s": uncertainty_s,
                           "assumed_interval_s": interval_s}
    return validate(result)


def _acquisition_extent(metadata):
    """Return one NMR experiment's recorded extent, never the EC duration."""
    parameters = metadata.get("acquisition_parameters", {})
    start, end = parameters.get("DATE_START"), parameters.get("DATE")
    try:
        if start is not None and end is not None:
            start, end = float(start), float(end)
        else:
            first = datetime.fromisoformat(str(metadata["acquisition_start"]).replace("Z", "+00:00"))
            last = datetime.fromisoformat(str(metadata["acquisition_end"]).replace("Z", "+00:00"))
            if (first.tzinfo is None) != (last.tzinfo is None):
                return None
            if first.tzinfo is None:
                # Naive times remain floating clock values; never ask the host
                # to assign a local timezone to an unqualified timestamp.
                epoch = datetime(1970, 1, 1)
                start = (first - epoch).total_seconds()
                end = (last - epoch).total_seconds()
            else:
                # Explicit offsets identify actual instants. Normalize these
                # to UTC so separately recorded groups retain correct offsets.
                start, end = first.timestamp(), last.timestamp()
        if math.isfinite(start) and math.isfinite(end) and end > start:
            return start, end
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    return None


def align_same_start(exp):
    """Apply the user's same-start assumption with explicit estimated row times.

    Real imported per-row times and durations stay intact. Unknown pseudo-2D
    row timing uses only that NMR experiment's recorded whole-acquisition span
    divided by its recorded row count; this is an estimate, not a clock repair.
    """
    result = deepcopy(exp)
    if not result["ec"]["time_s"] or not result["spectra"]:
        raise ValueError("Load both EC and NMR data before assuming the same acquisition start")
    experiments = {m.get("experiment_source"): m for m in result["metadata"].get("experiments", [])}
    groups = {}
    for spectrum in result["spectra"]:
        metadata = spectrum.setdefault("metadata", {})
        # Switching back from a custom cadence must use the original import,
        # not mistake an earlier user estimate for a measured row timestamp.
        for field in ("time_s", "duration_s"):
            original = "original_" + field
            if original in metadata:
                spectrum[field] = metadata[original]
                if metadata[original] is not None:
                    metadata["timing_basis" if field == "time_s" else "duration_basis"] = "preserved original imported per-row timing"
        key = metadata.get("experiment_source") or spectrum["source"]
        groups.setdefault(key, []).append(spectrum)
    group_metadata = {}
    extents = {}
    for key, spectra in groups.items():
        metadata = {**experiments.get(key, {}), **spectra[0].get("metadata", {})}
        group_metadata[key] = metadata
        extent = _acquisition_extent(metadata)
        if extent is not None:
            extents[key] = extent
    all_extents = list(extents.values()) + [extent for metadata in experiments.values() if (extent := _acquisition_extent(metadata)) is not None]
    origin = min((extent[0] for extent in all_extents), default=None)
    estimates, estimated_times, estimated_durations = [], 0, 0
    for key, spectra in groups.items():
        incomplete = [s for s in spectra if s.get("time_s") is None or s.get("duration_s") is None]
        if not incomplete:
            continue
        metadata = group_metadata[key]
        if key not in extents or metadata.get("extracted_processing_variant"):
            if any(s.get("time_s") is None for s in spectra):
                raise ValueError("Recorded NMR acquisition extent is unavailable for unknown row timing; supply an explicit manual cadence")
            # A known start with an unknown duration remains a timed point;
            # absence of a duration never licenses deriving one from EC data.
            continue
        start, end = extents[key]
        count = metadata.get("rows", len(spectra))
        if not isinstance(count, (int, float)) or not math.isfinite(count) or count < len(spectra) or int(count) != count:
            raise ValueError("Recorded NMR row count is invalid; supply an explicit manual cadence")
        count = int(count)
        interval = (end - start) / count
        offset = start - origin
        for index, spectrum in enumerate(spectra):
            row = spectrum["metadata"].get("row_index", index)
            if not isinstance(row, (int, float)) or int(row) != row or not 0 <= row < count:
                raise ValueError("Recorded NMR row index is invalid; supply an explicit manual cadence")
            if spectrum.get("time_s") is None:
                spectrum["metadata"].setdefault("original_time_s", spectrum.get("time_s"))
                spectrum["time_s"] = offset + row * interval
                spectrum["metadata"]["timing_basis"] = "estimated uniform row times from recorded whole-NMR acquisition span / row count; individual row times were not recorded"
                spectrum["metadata"]["timing_estimated"] = True
                estimated_times += 1
            if spectrum.get("duration_s") is None:
                spectrum["metadata"].setdefault("original_duration_s", spectrum.get("duration_s"))
                spectrum["duration_s"] = interval
                spectrum["metadata"]["duration_basis"] = "estimated uniform row interval, including unknown inter-row overhead"
                spectrum["metadata"]["duration_estimated"] = True
                estimated_durations += 1
        estimates.append({"experiment_source": key, "row_count": count, "span_s": end - start,
                          "interval_s": interval, "start_offset_s": offset})
    ec_year = str(result["ec"].get("start_time") or "")[:4]
    nmr_year = str(result["metadata"].get("start_time") or "")[:4]
    clock_note = f" Conflicting EC {ec_year} and NMR {nmr_year} absolute-clock years are ignored under this assumption." if ec_year.isdigit() and nmr_year.isdigit() and ec_year != nmr_year else " Absolute instrument-clock dates are ignored under this assumption."
    note = "User assumption: EC and NMR acquisitions started together at elapsed t=0." + clock_note
    if estimates:
        note += " Missing NMR row times/durations are estimated uniformly from each recorded NMR span and row count; automatic tune/match may vary the actual cadence."
    note += " Synchronization uncertainty is unknown."
    result["alignment"] = {"method": "manual", "assumption": "same_start", "offset_s": 0.0,
                           "uncertainty_s": None, "note": note,
                           "timing_basis": "recorded NMR span / recorded row count" if estimates else "preserved imported per-row timing",
                           "estimated_row_times": bool(estimated_times), "estimated_spectrum_count": estimated_times,
                           "estimated_duration_count": estimated_durations, "row_timing_estimates": estimates,
                           "assumed_interval_s": estimates[0]["interval_s"] if len(estimates) == 1 else None}
    if note not in result["warnings"]:
        result["warnings"].append(note)
    return validate(result)


def match_spectrum(exp, time_s):
    if not math.isfinite(time_s):
        raise ValueError("Selection time must be finite")
    empty = {"spectrum_id": None, "distance_s": None, "interval_start_s": None,
             "interval_end_s": None, "reason": "Time alignment is required"}
    if exp["alignment"]["method"] == "unaligned":
        return empty
    offset = exp["alignment"]["offset_s"]
    candidates = []
    for s in exp["spectra"]:
        if s.get("time_s") is None:
            continue
        start = s["time_s"] + offset
        end = start + (s.get("duration_s") or 0)
        dist = max(start - time_s, time_s - end, 0)
        candidates.append((dist, abs(time_s - start), s["id"], start, end))
    if not candidates:
        return empty
    if time_s < min(c[3] for c in candidates) or time_s > max(c[4] for c in candidates):
        return {**empty, "reason": "Outside the available NMR acquisition range"}
    dist, _, sid, start, end = min(candidates)
    return {"spectrum_id": sid, "distance_s": dist, "interval_start_s": start,
            "interval_end_s": end, "reason": "inside acquisition interval" if dist == 0 else "nearest spectrum; outside acquisition interval"}


def peak_integral(spectrum, low, high):
    """Signed raw integral (intensity·ppm), no silent normalization or baseline fit."""
    lo, hi = sorted((low, high))
    x, y = np.array(spectrum["ppm"]), np.array(spectrum["intensity"])
    order = np.argsort(x)
    x, y = x[order], y[order]
    if lo < x[0] or hi > x[-1] or lo == hi:
        raise ValueError("Peak integration bounds must lie inside spectral axis")
    middle = (x > lo) & (x < hi)
    xx = np.r_[lo, x[middle], hi]
    yy = np.r_[np.interp(lo, x, y), y[middle], np.interp(hi, x, y)]
    return float(np.trapezoid(yy, xx))
