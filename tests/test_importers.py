"""Parser invariants and optional real-data verification (raw files stay private)."""
from pathlib import Path
import os

import numpy as np
import pytest

from ecnmr.importers import ImportDataError, load_ec, load_nmr


def jcamp(path, values):
    path.write_text("##TITLE= Synthetic test data\n" + "\n".join(f"##${k}= {v}" for k, v in values.items()) + "\n##END=\n")


def make_bruker(tmp_path, matrix=False, big=False, scale=2, pseudo=True):
    exp = tmp_path / "1"
    proc = exp / "pdata" / "1"
    proc.mkdir(parents=True)
    jcamp(exp / "acqus", {"NUC1": "<7Li>", "PULPROG": "<ATM_zg_2D>" if matrix and pseudo else "<zg>", "DATE_START": 1700000000, "DATE": 1700000010})
    jcamp(proc / "procs", {"SI": 8, "SF": 100, "SW_p": 800, "OFFSET": 6, "BYTORDP": int(big), "DTYPP": 0, "NC_proc": scale, "XDIM": 4 if matrix else 8})
    dtype = ">i4" if big else "<i4"
    if matrix:
        a = np.arange(32).reshape(4, 8)
        jcamp(proc / "proc2s", {"SI": 4, "XDIM": 2})
        # Explicit block-major storage, independent of the reader's routine.
        blocks = [a[y:y+2, x:x+4].ravel() for y in (0, 2) for x in (0, 4)]
        np.concatenate(blocks).astype(dtype).tofile(proc / "2rr")
    else:
        a = np.array([1, -2, 3, -4, 5, 6, 7, 8])
        a.astype(dtype).tofile(proc / "1r")
    return exp, proc, a


def test_bruker_1d_endian_scaling_ppm_and_interval(tmp_path):
    exp, _, a = make_bruker(tmp_path, big=True, scale=-2)
    spectra, metadata, warnings = load_nmr(exp)
    assert len(spectra) == 1
    assert spectra[0]["intensity"] == (a / 4).tolist()
    assert spectra[0]["ppm"] == [6, 5, 4, 3, 2, 1, 0, -1]
    assert spectra[0]["time_s"] == 0
    assert spectra[0]["duration_s"] == 10
    assert metadata["nucleus"] == "7Li"
    assert warnings == []


def test_pseudo2d_tiled_rows_do_not_fabricate_timing(tmp_path):
    exp, _, a = make_bruker(tmp_path, matrix=True, scale=3)
    spectra, _, warnings = load_nmr(exp)
    assert len(spectra) == 4
    np.testing.assert_array_equal([s["intensity"] for s in spectra], a * 8)
    assert all(s["time_s"] is None and s["duration_s"] is None for s in spectra)
    assert "no per-row acquisition timestamps" in warnings[0]


def test_true_2d_is_not_treated_as_temporal_series(tmp_path):
    exp, _, _ = make_bruker(tmp_path, matrix=True, pseudo=False)
    with pytest.raises(ImportDataError, match="True 2D"):
        load_nmr(exp)


def test_incomplete_spectrum_rejected(tmp_path):
    exp, proc, _ = make_bruker(tmp_path)
    (proc / "1r").write_bytes(b"\x00" * 8)
    with pytest.raises(ImportDataError, match="incomplete"):
        load_nmr(exp)


def test_processing_variants_are_not_duplicate_acquisitions(tmp_path):
    exp, proc, _ = make_bruker(tmp_path, matrix=True)
    variant = proc.parent / "999"
    variant.mkdir()
    (variant / "procs").write_bytes((proc / "procs").read_bytes())
    np.zeros(8, dtype="<i4").tofile(variant / "1r")
    assert len(load_nmr(exp)[0]) == 4


def write_mpt(path, names, rows):
    path.write_text("EC-Lab ASCII FILE\nNb header lines : 4\nAcquisition started on : 02/07/2025 11:10:00\n" + "\t".join(names) + "\n" + "\n".join("\t".join(map(str, row)) for row in rows) + "\n")


def test_mpt_decimal_comma_units_and_signed_capacity(tmp_path):
    path = tmp_path / "test.mpt"
    write_mpt(path, ["time/s", "Ewe/mV", "I/A"], [[0, "3000,5", "0,001"], [3600, 3100, "0,001"], [7200, 3200, "-0,001"]])
    ec = load_ec(path)
    assert ec["voltage_V"] == [3.0005, 3.1, 3.2]
    assert ec["current_mA"] == [1, 1, -1]
    assert ec["capacity_mAh"] == [0, 1, 1]
    assert ec["start_time"] is None  # ambiguous locale and timezone not guessed
    assert "02/07/2025" in ec["metadata"]["acquisition_start_text"]


def test_mpt_derives_current_from_charge_never_control(tmp_path):
    path = tmp_path / "test.mpt"
    write_mpt(path, ["time/s", "Ewe/V", "dq/mA.h", "control/V/mA", "(Q-Qo)/mA.h"], [[0, 3, 0, 4.3, 0], [10, 3.1, 0.001, 4.3, 0.001], [10, 3.1, 0, 4.3, 0.001], [20, 3.2, -0.001, 4.3, 0]])
    ec = load_ec(path)
    assert ec["current_mA"] == [None, 0.36, None, -0.36]
    assert "interval-average" in ec["metadata"]["current_method"]
    assert ec["capacity_mAh"] == [0, 0.001, 0.001, 0]


def test_incomplete_mpt_row_rejected(tmp_path):
    path = tmp_path / "test.mpt"
    write_mpt(path, ["time/s", "Ewe/V"], [[0, 3], [1]])
    with pytest.raises(ImportDataError, match="Incomplete MPT row"):
        load_ec(path)


def test_time_reset_rejected(tmp_path):
    path = tmp_path / "test.mpt"
    write_mpt(path, ["time/s", "Ewe/V"], [[1, 3], [0, 3]])
    with pytest.raises(ImportDataError, match="time decreases"):
        load_ec(path)


REAL_ROOT = os.environ.get("ECNMR_REAL_DATA")


@pytest.mark.skipif(not REAL_ROOT, reason="set ECNMR_REAL_DATA to extracted private uploads")
def test_real_nmr_rows_axis_scaling_and_duplicate_extraction():
    root = Path(REAL_ROOT)
    spectra, metadata, warnings = load_nmr(root / "4")
    assert len(spectra) == 64
    assert len(spectra[0]["ppm"]) == 4096
    assert metadata["start_time"] == "2025-07-02T09:09:51+00:00"
    assert metadata["nucleus"] == "7Li"
    assert all(s["time_s"] is None for s in spectra)
    proc = root / "4" / "pdata" / "1"
    raw = np.fromfile(proc / "2rr", dtype="<i4").reshape(64, 4096)
    # The supplied XDIM spans the entire matrix, so reshape is an independent oracle.
    np.testing.assert_array_equal(np.array([s["intensity"] for s in spectra]), raw * 64.0)
    assert spectra[0]["ppm"][0] == pytest.approx(1103.38728130348)
    assert spectra[0]["ppm"][-1] == pytest.approx(1103.38728130348 - 4095 * 250000 / (155.591211 * 4096))
    row = load_nmr(root / "4" / "pdata" / "999")[0][0]
    np.testing.assert_array_equal(row["intensity"], spectra[50]["intensity"])
    assert row["time_s"] is None
    assert warnings


@pytest.mark.skipif(not REAL_ROOT, reason="set ECNMR_REAL_DATA to extracted private uploads")
def test_real_mpr_counts_units_current_reconstruction_and_timestamp():
    path = next(Path(REAL_ROOT).rglob("*.mpr"))
    ec = load_ec(path)
    assert len(ec["time_s"]) == 98790
    assert ec["time_s"][-1] == pytest.approx(186964.6980535169)
    assert ec["start_time"] == "2024-05-31T04:54:03.166000"
    assert ec["voltage_V"][0] == pytest.approx(3.0489993)
    assert min(ec["voltage_V"]) == pytest.approx(2.4974334)
    assert max(ec["voltage_V"]) == pytest.approx(4.5422616)
    assert ec["current_mA"][0] is None
    assert ec["current_mA"][2] == pytest.approx(0.19566633, rel=1e-6)
    assert ec["capacity_mAh"][-1] == pytest.approx(0.924961603)
    assert "I/mA" not in ec["metadata"]["columns"]
    assert "interval-average" in ec["metadata"]["current_method"]
    assert ec["metadata"]["timestamp_timezone"].startswith("unspecified")


def test_ec_directory_requires_unambiguous_measurement(tmp_path):
    path = tmp_path / "single.mpt"
    write_mpt(path, ["time/s", "Ewe/V"], [[0, 3], [1, 3.1]])
    assert load_ec(tmp_path)["voltage_V"] == [3, 3.1]
    (tmp_path / "other.mpt").write_bytes(path.read_bytes())
    with pytest.raises(ImportDataError, match="2 measurement files"):
        load_ec(tmp_path)


def test_synthetic_example_generator_produces_standard_formats(tmp_path):
    from scripts.generate_examples import generate
    ec_path, nmr_path = generate(tmp_path / "synthetic", tmp_path / "synthetic.zip")
    ec = load_ec(ec_path)
    spectra, metadata, warnings = load_nmr(nmr_path)
    assert len(ec["time_s"]) == 721
    assert len(spectra) == 6
    assert [s["time_s"] for s in spectra] == [0, 120, 240, 360, 480, 600]
    assert all(s["duration_s"] == 90 for s in spectra)
    assert all(len(s["intensity"]) == 512 for s in spectra)
    assert metadata["nucleus"] == "7Li"
    assert all("SYNTHETIC" in s["metadata"]["title"] for s in spectra)
    assert warnings == []
