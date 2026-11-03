"""Shared representation and explicit timeline alignment. All times are seconds."""
from __future__ import annotations

from copy import deepcopy
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
            spectrum["time_s"] = i * interval_s
            spectrum["metadata"]["timing_basis"] = "operator-assumed uniform cadence"
    if duration_s is not None:
        for spectrum in result["spectra"]:
            spectrum["duration_s"] = duration_s
            spectrum["metadata"]["duration_basis"] = "operator supplied"
    result["alignment"] = {"method": method, "offset_s": float(offset_s),
                           "uncertainty_s": uncertainty_s,
                           "assumed_interval_s": interval_s}
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
