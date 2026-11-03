"""Completed-file scientific importers; no vendor installation or device access.

Bruker processed spectra are read with nmrglue (tiling, endian and NC_proc).
BioLogic binary support is provided by galvani, a third-party GPL reader, and
is deliberately limited to completed files. Raw inputs are never modified.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

import numpy as np


class ImportDataError(ValueError):
    """An input cannot be interpreted without guessing scientific information."""


def _values(array: Any) -> list:
    return [float(x) if np.isfinite(x) else None for x in np.asarray(array, dtype=float)]


def _column(data: dict, alternatives: tuple[str, ...]):
    for name in alternatives:
        if name in data:
            return np.asarray(data[name], dtype=float), name
    return None, None


def _normalize_ec(columns: dict, path: Path, metadata: dict, start_time=None):
    t, time_column = _column(columns, ("time/s", "Time/s", "time / s"))
    if t is None or not len(t) or not np.isfinite(t).all():
        raise ImportDataError("A nonempty, finite time/s column is required.")
    if np.any(np.diff(t) < 0):
        raise ImportDataError("EC time decreases; split/reconcile interrupted runs before importing.")
    v, voltage_column = _column(columns, ("Ewe/V", "<Ewe>/V", "<Ewe/V>", "Ecell/V"))
    if v is None:
        v, voltage_column = _column(columns, ("Ewe/mV", "Ecell/mV"))
        if v is not None:
            v = v / 1000
    current, current_column = _column(columns, ("I/mA", "<I>/mA"))
    current_method = "exported measurement"
    if current is None:
        current, current_column = _column(columns, ("I/A", "<I>/A"))
        if current is not None:
            current = current * 1000
    warnings = list(metadata.get("warnings", []))
    if current is None:
        dq, current_column = _column(columns, ("dq/mA.h", "dQ/mA.h"))
        if dq is not None:
            # The increment stored at row i covers the preceding time interval.
            # A zero-duration interval has no definable average current.
            dt = np.r_[np.nan, np.diff(t)]
            current = np.divide(dq * 3600, dt, out=np.full(len(t), np.nan), where=dt > 0)
            current_method = "interval-average current derived as 3600 × dq(mAh) / dt(s)"
            warnings.append("Measured current is absent. Current is reconstructed from charge increments over each preceding interval; the first/zero-duration value is unavailable. Mixed-unit control/V/mA is not current.")
    if current is None:
        current = np.full(len(t), np.nan)
        current_method = "unavailable"
        warnings.append("No measured current or charge increments available; current is unavailable.")
    if v is None:
        v = np.full(len(t), np.nan)
        warnings.append("Voltage is unavailable.")
    q, capacity_column = _column(columns, ("(Q-Qo)/mA.h", "Q charge/discharge/mA.h", "Capacity/mA.h"))
    capacity_method = "exported quantity: " + str(capacity_column)
    if q is None and np.isfinite(current).all():
        q = np.r_[0, np.cumsum((current[1:] + current[:-1]) * 0.5 * np.diff(t) / 3600)]
        capacity_method = "signed charge from trapezoidal integral of exported current; zero at first sample"
    if q is None:
        q = np.full(len(t), np.nan)
        capacity_method = "unavailable"
    metadata.update({"columns": list(columns), "time_column": time_column,
                     "voltage_column": voltage_column, "current_column": current_column,
                     "current_method": current_method, "capacity_column": capacity_column,
                     "capacity_method": capacity_method, "point_count": len(t),
                     "time_units": "s", "voltage_units": "V", "current_units": "mA",
                     "capacity_units": "mAh", "time_origin_s": float(t[0]),
                     "warnings": warnings})
    for name in ("Ns", "half cycle", "cycle number", "Q charge/discharge/mA.h", "control/V/mA"):
        if name in columns:
            metadata.setdefault("additional_columns", {})[name] = _values(columns[name])
    return {"time_s": _values(t), "voltage_V": _values(v), "current_mA": _values(current),
            "capacity_mAh": _values(q), "source": str(path), "start_time": start_time,
            "metadata": metadata}


def load_ec(path: str | Path) -> dict:
    """Load a completed BioLogic .mpt export or .mpr file, preserving units.

    MPR OLE timestamps are local wall times with unknown timezone, so remain
    naive ISO strings. Callers must never silently compare them with UTC NMR.
    """
    path = Path(path).expanduser().resolve()
    if path.is_dir():
        candidates = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in (".mpr", ".mpt"))
        if len(candidates) != 1:
            raise ImportDataError(f"EC folder contains {len(candidates)} measurement files; select exactly one .mpr or .mpt file.")
        path = candidates[0]
    if path.suffix.lower() == ".mpr":
        from galvani.BioLogic import MPRfile
        # Passing an owned file object avoids leaking a descriptor in galvani.
        with path.open("rb") as stream:
            mpr = MPRfile(stream)
        columns = {name: mpr.data[name] for name in mpr.data.dtype.names}
        stamp = getattr(mpr, "timestamp", None)
        metadata = {"format": "BioLogic MPR", "reader": "galvani", "module_version": mpr.version,
                    "settings_start_date": str(mpr.startdate),
                    "log_end_date": str(getattr(mpr, "enddate", "")),
                    "timestamp_timezone": "unspecified; requires operator confirmation",
                    "timestamp_source": "MPR LOG OLE timestamp"}
        filename_date = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", path.name)
        if filename_date and stamp:
            day, month, year = map(int, filename_date.groups())
            if (year, month, day) != (stamp.year, stamp.month, stamp.day):
                metadata["warnings"] = ["EC filename date conflicts with the MPR LOG acquisition timestamp; filename is not synchronization evidence."]
        siblings = list(path.parent.glob("*.mps"))
        if len(siblings) == 1:
            protocol = siblings[0].read_text(encoding="cp1252", errors="replace")
            metadata["protocol_file"] = str(siblings[0])
            metadata["protocol_text"] = protocol
            metadata["protocol_note"] = "Context only; copied sample descriptions and filenames are not synchronization evidence."
        return _normalize_ec(columns, path, metadata, stamp.isoformat() if stamp else None)
    if path.suffix.lower() != ".mpt":
        raise ImportDataError("EC input must be a completed .mpt or .mpr file.")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        text, encoding = raw.decode("cp1252"), "cp1252"
    lines = text.splitlines()
    match = re.search(r"Nb header lines\s*:\s*(\d+)", text)
    if not match:
        raise ImportDataError("EC-Lab MPT header line count is missing.")
    header_count = int(match.group(1))
    if header_count < 2 or header_count >= len(lines):
        raise ImportDataError("MPT header line count is invalid or the data table is empty.")
    names = [name.strip() for name in lines[header_count - 1].split("\t")]
    while names and not names[-1]:
        names.pop()
    required = {i for i, n in enumerate(names) if n in {"time/s", "Time/s", "time / s", "Ewe/V", "<Ewe>/V", "<Ewe/V>", "Ecell/V", "Ewe/mV", "Ecell/mV", "I/mA", "<I>/mA", "I/A", "<I>/A", "dq/mA.h", "dQ/mA.h", "(Q-Qo)/mA.h", "Q charge/discharge/mA.h", "Capacity/mA.h", "Ns", "half cycle", "cycle number", "control/V/mA"}}
    columns = {names[i]: [] for i in required}
    for line_no, cells in enumerate(csv.reader(lines[header_count:], delimiter="\t"), header_count + 1):
        if not cells or not any(cells):
            continue
        if len(cells) < len(names):
            raise ImportDataError(f"Incomplete MPT row {line_no}; import completed files only.")
        for i in required:
            value = cells[i].strip().replace(",", ".")
            try:
                columns[names[i]].append(float(value) if value else np.nan)
            except ValueError as exc:
                raise ImportDataError(f"Nonnumeric value in {names[i]} at row {line_no}.") from exc
    metadata = {"format": "BioLogic MPT", "encoding": encoding,
                "header_text": "\n".join(lines[:header_count - 1]),
                "original_columns": names, "timestamp_timezone": "unspecified"}
    stamp_match = re.search(r"Acquisition started on\s*:\s*([^\r\n]+)", text)
    # Export date strings are locale-dependent. Preserve them verbatim, rather
    # than silently choosing day/month ordering or local timezone.
    if stamp_match:
        metadata["acquisition_start_text"] = stamp_match.group(1).strip()
    return _normalize_ec(columns, path, metadata)


def _iso_epoch(value):
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat()


def _processed_directories(path: Path):
    if path.is_file():
        path = path.parent
    if (path / "procs").is_file() and ((path / "1r").is_file() or (path / "2rr").is_file()):
        return [path]
    dirs = sorted({p.parent for p in path.rglob("procs") if (p.parent / "1r").is_file() or (p.parent / "2rr").is_file()})
    # Multiple procno values are processing variants, not new acquisitions.
    # Prefer a 2rr parent series to an extracted 1r row (e.g. procno 999).
    groups = {}
    for directory in dirs:
        experiment = directory.parent.parent if directory.parent.name == "pdata" else directory
        key = (0 if (directory / "2rr").is_file() else 1,
               int(directory.name) if directory.name.isdigit() else 10**9, str(directory))
        if experiment not in groups or key < groups[experiment][0]:
            groups[experiment] = (key, directory)
    return [v[1] for v in groups.values()]


def load_nmr(path: str | Path) -> tuple[list, dict, list]:
    """Load processed 1D acquisitions or explicitly identified pseudo-2D rows.

    A pseudo-2D array is a collection of spectra but not necessarily a timed
    series. Row timestamps remain unknown unless supplied separately by the
    operator. Real 2D experiments are rejected, not relabelled as operando rows.
    """
    import nmrglue as ng
    path = Path(path).expanduser().resolve()
    dirs = _processed_directories(path)
    if not dirs:
        raise ImportDataError("No processed Bruker 1r/2rr with procs found. Process spectra in TopSpin first.")
    spectra, warnings, experiments = [], [], []
    genuine_1d = []
    for directory in dirs:
        is_matrix = (directory / "2rr").is_file()
        binary_name = "2rr" if is_matrix else "1r"
        experiment = directory.parent.parent if directory.parent.name == "pdata" else directory
        acqu_path = experiment / "acqus"
        acqu = ng.bruker.read_jcamp(str(acqu_path)) if acqu_path.is_file() else {}
        procs = ng.bruker.read_jcamp(str(directory / "procs"))
        proc2 = ng.bruker.read_jcamp(str(directory / "proc2s")) if (directory / "proc2s").is_file() else {}
        title_path = directory / "title"
        title = title_path.read_text(errors="replace").strip() if title_path.is_file() else ""
        pulse = str(acqu.get("PULPROG", ""))
        pseudo = "pseudo" in title.lower() or pulse.lower().startswith("atm_zg")
        if is_matrix and not pseudo:
            raise ImportDataError("2rr is not explicitly identified as pseudo-2D. True 2D NMR is outside this viewer's 1D-series scope.")
        n = int(procs.get("SI", 0))
        rows = int(proc2.get("SI", 0)) if is_matrix else 1
        if n <= 0 or rows <= 0:
            raise ImportDataError("Processed dimensions SI are missing or invalid.")
        if int(procs.get("DTYPP", 0)) not in (0, 2):
            raise ImportDataError("Unsupported Bruker processed data type DTYPP.")
        bytes_per = 8 if int(procs.get("DTYPP", 0)) == 2 else 4
        xdim = int(procs.get("XDIM", n))
        ydim = int(proc2.get("XDIM", rows)) if is_matrix else 1
        if xdim <= 0 or ydim <= 0:
            raise ImportDataError("Invalid processed tile dimensions XDIM.")
        padded_n = ((n + xdim - 1) // xdim) * xdim
        padded_rows = ((rows + ydim - 1) // ydim) * ydim
        expected = padded_n * padded_rows * bytes_per
        if (directory / binary_name).stat().st_size != expected:
            raise ImportDataError("Processed binary size disagrees with SI/XDIM; file may be incomplete.")
        _, data = ng.bruker.read_pdata(str(directory), bin_files=[binary_name],
                                        scale_data=True, shape=(rows, n) if is_matrix else (n,),
                                        submatrix_shape=(ydim, xdim) if is_matrix else (xdim,))
        if np.shape(data) != ((rows, n) if is_matrix else (n,)):
            raise ImportDataError("Processed array dimensions disagree with metadata.")
        sf = float(procs.get("SF", 0))
        sw = float(procs.get("SW_p", 0))
        if sf <= 0 or sw <= 0 or "OFFSET" not in procs:
            raise ImportDataError("Chemical-shift axis requires positive SF, SW_p and OFFSET.")
        ppm = (float(procs["OFFSET"]) - np.arange(n) * sw / sf / n).tolist()
        start, end = acqu.get("DATE_START"), acqu.get("DATE")
        extracted = (directory / "used_from").is_file()
        timing_known = not is_matrix and not extracted and start is not None and end is not None and float(end) >= float(start)
        selected_keys = ("NUC1", "SFO1", "SW_h", "SW", "O1", "O1P", "TD", "NS", "DS", "D", "P", "IN", "PULPROG", "PARMODE", "DATE_START", "DATE", "AQSEQ")
        meta = {"experiment_source": str(experiment), "processed_source": str(directory),
                "format": "Bruker processed pseudo-2D" if is_matrix else "Bruker processed 1D",
                "nucleus": acqu.get("NUC1", "unknown"), "title": title,
                "acquisition_start": _iso_epoch(start), "acquisition_end": _iso_epoch(end),
                "acquisition_parameters": {k: acqu[k] for k in selected_keys if k in acqu},
                "processing_parameters": {k: procs[k] for k in ("SI", "SF", "SW_p", "OFFSET", "BYTORDP", "DTYPP", "NC_proc", "XDIM") if k in procs},
                "rows": rows, "points_per_spectrum": n,
                "intensity_units": "a.u.; stored values × 2**NC_proc", "ppm_formula": "OFFSET - index * SW_p / (SF * SI)",
                "timing_source": "DATE_START/DATE" if timing_known else "row timestamps unavailable",
                "extracted_processing_variant": extracted}
        experiments.append(meta)
        if is_matrix:
            warnings.append(f"{experiment.name}: {rows} pseudo-2D rows have no per-row acquisition timestamps. Automatic tune/match may vary cadence. Supply a documented manual cadence/offset; uniform timing is an assumption, not measured synchronization.")
        elif not timing_known:
            warnings.append(f"{directory.name}: acquisition interval unavailable; extraction/processing timestamps do not identify an acquisition.")
        for row_index, trace in enumerate(data if is_matrix else [data]):
            sid = f"nmr-{len(experiments)}-row-{row_index + 1}"
            s = {"id": sid, "label": f"{experiment.name} · row {row_index + 1}" if is_matrix else f"{experiment.name} · proc {directory.name}",
                 "time_s": None, "duration_s": float(end) - float(start) if timing_known else None,
                 "ppm": ppm, "intensity": _values(trace), "source": str(directory / binary_name),
                 "metadata": {**meta, "row_index": row_index, "absolute_start": _iso_epoch(start) if timing_known else None}}
            spectra.append(s)
            if timing_known:
                genuine_1d.append((s, float(start)))
    if genuine_1d:
        origin = min(float(m["acquisition_parameters"]["DATE_START"]) for m in experiments if "DATE_START" in m["acquisition_parameters"])
        for s, stamp in genuine_1d:
            s["time_s"] = stamp - origin
    starts = [m["acquisition_start"] for m in experiments if m["acquisition_start"]]
    metadata = {"source": str(path), "reader": "nmrglue", "experiments": experiments,
                "start_time": min(starts) if starts else None,
                "nucleus": experiments[0]["nucleus"] if len({m["nucleus"] for m in experiments}) == 1 else "mixed",
                "timing": "acquisition-relative where available; unknown row times remain null",
                "processing_variants": "one preferred procno per acquisition; explicit procno paths honored"}
    return spectra, metadata, warnings
