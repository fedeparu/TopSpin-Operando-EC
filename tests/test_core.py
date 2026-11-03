"""Scientific timing, failure and recovery acceptance checks without wall-clock sleeps."""
from copy import deepcopy
import json
import sqlite3

import pytest

from ecnmr.controller import Controller
from ecnmr.model import align, match_spectrum, peak_integral, validate
from ecnmr.synthetic import demo


def test_alignment_requires_operator_values_and_retains_provenance():
    source = demo()
    source["alignment"]["method"] = "unaligned"
    for spectrum in source["spectra"]:
        spectrum["time_s"] = None
        spectrum["duration_s"] = None
    assert match_spectrum(source, 350)["spectrum_id"] is None
    aligned = align(source, offset_s=120, interval_s=300, duration_s=200, uncertainty_s=15)
    assert source["spectra"][1]["time_s"] is None  # Original metadata is never mutated.
    assert aligned["alignment"]["uncertainty_s"] == 15
    assert aligned["spectra"][1]["metadata"]["timing_basis"] == "operator-assumed uniform cadence"
    assert match_spectrum(aligned, 420)["spectrum_id"] == "synthetic-02"
    assert match_spectrum(aligned, 620)["interval_end_s"] == 620
    assert match_spectrum(aligned, 120 - 1)["spectrum_id"] is None
    assert match_spectrum(aligned, 10**6)["spectrum_id"] is None
    # A gap is explicitly reported, never mislabeled as simultaneous acquisition.
    gap = match_spectrum(aligned, 360)
    assert gap["spectrum_id"] == "synthetic-01"
    assert gap["distance_s"] == 40
    assert "outside acquisition interval" in gap["reason"]


def test_peak_integral_uses_ascending_axis_and_interpolated_boundary_values():
    spectrum = {"ppm": [3., 2., 1., 0.], "intensity": [6., 4., 2., 0.]}
    # y=2x integrated over [0.5, 2.5] gives 6, even with the normal reversed ppm axis.
    assert peak_integral(spectrum, 2.5, 0.5) == pytest.approx(6)
    assert peak_integral({"ppm": [0., 1., 2.], "intensity": [-1., -1., -1.]}, 0, 2) == -2
    with pytest.raises(ValueError, match="inside spectral axis"):
        peak_integral(spectrum, -1, 2)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1])
def test_invalid_timing_uncertainty_rejected(bad):
    with pytest.raises(ValueError):
        align(demo(), uncertainty_s=bad)


def test_simulation_progress_completion_and_analysis_selection_preservation(tmp_path):
    c = Controller(tmp_path)
    try:
        source = demo()
        source["ec"]["metadata"]["additional_columns"] = {"cycle number": [1] * 721}
        c.replace(source)
        c.analysis({"selected_ids": ["synthetic-01"], "peak_min": 1, "peak_max": 4})
        c.action("prepare", speed=1)
        c.action("start")
        c.advance(239)
        assert c.status()["available_spectra"] == 0  # Only completed acquisitions are visible.
        assert c.status()["available_ec"] == 24
        assert len(c.view()["ec"]["metadata"]["additional_columns"]["cycle number"]) == 24
        c.advance(1)
        assert [s["id"] for s in c.view()["spectra"]] == ["synthetic-01"]
        assert c.view()["analysis"]["selected_ids"] == ["synthetic-01"]
        c.advance(300)
        assert c.status()["available_spectra"] == 2
        c.advance(100000)
        assert c.status()["state"] == "completed"
        assert c.status()["elapsed_s"] == 7200
        assert c.status()["available_spectra"] == 24
        assert c.status()["available_ec"] == 721
        assert any(event["kind"] == "completed" for event in c.events())
    finally:
        c.close()


def test_communication_loss_and_failure_cannot_invent_measurements(tmp_path):
    c = Controller(tmp_path)
    try:
        c.action("prepare", speed=1)
        c.action("start")
        c.advance(300)
        before = c.view()
        c.action("disconnect")
        c.advance(100000)
        assert c.status()["state"] == "paused"
        assert c.status()["elapsed_s"] == 300
        assert c.view() == before
        c.action("reconnect")
        c.advance(240)
        assert c.status()["available_spectra"] == 2
        c.action("fail")
        captured = c.view()
        c.advance(100000)
        assert c.view() == captured
        assert c.status()["state"] == "error"
        assert "preserved" in c.status()["error"]
        c.action("stop")
        c.advance(100000)
        assert c.view() == captured
    finally:
        c.close()


def test_running_recovery_requires_explicit_resume_and_restores_analysis(tmp_path):
    c = Controller(tmp_path)
    c.analysis({"selected_ids": ["synthetic-01"], "peak_min": -2, "peak_max": 7})
    c.action("prepare", speed=1)
    c.action("start")
    c.advance(540)
    original = c.view()
    # Simulate process termination without Controller.close(); writes are already committed.
    c.db.close()
    recovered = Controller(tmp_path)
    try:
        assert recovered.status()["state"] == "paused"
        assert recovered.status()["elapsed_s"] == 540
        assert recovered.view() == original
        recovered.advance(10000)
        assert recovered.status()["available_spectra"] == 2
        recovered.action("resume")
        recovered.advance(300)
        assert recovered.status()["available_spectra"] == 3
        recovered.action("stop")
        recovered.set_mode("offline")
        assert recovered.status()["available_spectra"] == 24
        assert recovered.status()["error"] is None
    finally:
        recovered.close()


def test_corrupted_recovery_state_falls_back_without_partial_loading(tmp_path):
    c = Controller(tmp_path)
    c.close()
    db = sqlite3.connect(tmp_path / "recovery.sqlite3")
    db.execute("DELETE FROM snapshot WHERE key='state'")
    db.commit()
    db.close()
    recovered = Controller(tmp_path)
    try:
        assert recovered.status()["mode"] == "offline"
        assert recovered.status()["state"] == "ready"
        assert "Invalid recovery snapshot" in recovered.status()["error"]
    finally:
        recovered.close()


def test_late_background_poll_after_shutdown_cannot_write_closed_database(tmp_path):
    c = Controller(tmp_path)
    c.action("prepare")
    c.action("start")
    c.close()
    c.tick()
    c.advance(100)
    c.close()  # Both application shutdown paths may safely invoke cleanup.


def test_hardware_and_ambiguous_recordings_fail_closed(tmp_path):
    c = Controller(tmp_path)
    try:
        with pytest.raises(ValueError, match="unavailable"):
            c.set_mode("live")
        unaligned = demo()
        unaligned["alignment"]["method"] = "unaligned"
        unaligned["spectra"][0]["time_s"] = None
        c.replace(unaligned)
        with pytest.raises(ValueError, match="Align"):
            c.action("prepare")
        c.set_mode("simulation")
        with pytest.raises(ValueError, match="alignment"):
            c.action("start")
        assert c.status()["state"] == "ready"
        assert not c.status()["hardware_validated"]
    finally:
        c.close()


@pytest.mark.parametrize("mutate", [
    lambda d: d["ec"]["time_s"].__setitem__(1, -1),
    lambda d: d["ec"]["time_s"].__setitem__(1, "10"),
    lambda d: d["spectra"][0]["ppm"].__setitem__(1, d["spectra"][0]["ppm"][0]),
    lambda d: d["spectra"][0].__setitem__("duration_s", -1),
    lambda d: d["metadata"].__setitem__("bad", float("nan")),
])
def test_saved_session_rejects_misleading_or_nonfinite_data(mutate):
    source = demo()
    mutate(source)
    with pytest.raises(ValueError):
        validate(source)
