"""Scientific timing, failure and recovery acceptance checks without wall-clock sleeps."""
from copy import deepcopy
import json
import sqlite3

import pytest

from ecnmr.controller import Controller
from ecnmr.model import align, align_same_start, match_spectrum, peak_integral, validate
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


def whole_span_series(rows=64, span=74397):
    source = demo()
    metadata = {"experiment_source": "recorded-nmr/4", "rows": rows,
                "acquisition_start": "2025-07-02T09:09:51+00:00",
                "acquisition_end": "2025-07-03T05:49:48+00:00",
                "acquisition_parameters": {"DATE_START": 1751447391, "DATE": 1751447391 + span},
                "timing_source": "row timestamps unavailable"}
    source["metadata"] = {"experiments": [deepcopy(metadata)], "start_time": metadata["acquisition_start"]}
    source["ec"]["start_time"] = "2024-05-31T04:54:03.166000"
    source["spectra"] = [{"id": f"recorded-{i+1}", "label": f"Row {i+1}", "source": "recorded-nmr/4/pdata/1/2rr",
                          "time_s": None, "duration_s": None, "ppm": [1., 0.], "intensity": [2., 1.],
                          "metadata": {**deepcopy(metadata), "row_index": i}}
                         for i in range(rows)]
    source["alignment"]["method"] = "unaligned"
    return source


def test_same_start_uses_recorded_nmr_span_not_ec_length_and_retains_unknown_source_times():
    source = whole_span_series()
    before = deepcopy(source)
    result = align_same_start(source)
    assert source == before
    assert result["alignment"]["method"] == "manual"
    assert result["alignment"]["assumption"] == "same_start"
    assert result["alignment"]["offset_s"] == 0
    assert result["alignment"]["uncertainty_s"] is None
    assert result["alignment"]["estimated_spectrum_count"] == 64
    assert result["alignment"]["assumed_interval_s"] == 1162.453125
    assert result["spectra"][0]["time_s"] == 0
    assert result["spectra"][-1]["time_s"] + result["spectra"][-1]["duration_s"] == 74397
    assert result["spectra"][-1]["time_s"] > result["ec"]["time_s"][-1]
    assert "2024" in result["alignment"]["note"] and "2025" in result["alignment"]["note"]
    assert "unknown" in result["alignment"]["note"]
    for original, estimated in zip(source["spectra"], result["spectra"]):
        assert estimated["metadata"]["original_time_s"] is None
        assert estimated["metadata"]["original_duration_s"] is None
        assert estimated["metadata"]["acquisition_parameters"] == original["metadata"]["acquisition_parameters"]
        assert estimated["metadata"]["timing_estimated"] is True
        assert "estimated" in estimated["metadata"]["timing_basis"]
    assert match_spectrum(result, 1.5 * 1162.453125)["spectrum_id"] == "recorded-2"


def test_same_start_is_idempotent_and_replaces_custom_estimates_from_original_unknowns():
    same = align_same_start(whole_span_series())
    assert align_same_start(same) == same
    custom = align(same, offset_s=100, interval_s=60, duration_s=45)
    restored = align_same_start(custom)
    assert restored["alignment"]["offset_s"] == 0
    assert restored["spectra"][1]["time_s"] == 1162.453125
    assert restored["spectra"][1]["duration_s"] == 1162.453125
    assert restored["spectra"][1]["metadata"]["original_time_s"] is None


def test_same_start_preserves_actual_imported_row_times_even_after_manual_override():
    actual = demo()
    same = align_same_start(actual)
    assert [s["time_s"] for s in same["spectra"]] == [s["time_s"] for s in actual["spectra"]]
    assert [s["duration_s"] for s in same["spectra"]] == [s["duration_s"] for s in actual["spectra"]]
    assert not same["alignment"]["estimated_row_times"]
    custom = align(actual, interval_s=10, duration_s=5)
    assert custom["spectra"][1]["metadata"]["original_time_s"] == 300
    restored = align_same_start(custom)
    assert [s["time_s"] for s in restored["spectra"]] == [s["time_s"] for s in actual["spectra"]]
    assert [s["duration_s"] for s in restored["spectra"]] == [s["duration_s"] for s in actual["spectra"]]


def test_same_start_cannot_use_ec_extent_to_fill_unknown_nmr_timing():
    source = whole_span_series()
    source["metadata"].pop("experiments")
    for spectrum in source["spectra"]:
        spectrum["metadata"] = {"row_index": spectrum["metadata"]["row_index"]}
    with pytest.raises(ValueError, match="explicit manual cadence"):
        align_same_start(source)


def test_same_start_keeps_group_offsets_and_their_individual_recorded_cadences():
    source = whole_span_series(rows=2, span=100)
    for spectrum in source["spectra"]:
        spectrum["metadata"]["acquisition_parameters"] = {"DATE_START": 1000, "DATE": 1100}
    second_group = deepcopy(source["spectra"])
    for spectrum in second_group:
        spectrum["id"] += "-second"
        spectrum["metadata"].update({"experiment_source": "recorded-nmr/5", "acquisition_parameters": {"DATE_START": 1300, "DATE": 1500}})
    source["spectra"] += second_group
    source["metadata"]["experiments"] = []
    result = align_same_start(source)
    assert [s["time_s"] for s in result["spectra"]] == [0, 50, 300, 400]
    assert [s["duration_s"] for s in result["spectra"]] == [50, 50, 100, 100]


def test_same_start_iso_fallback_compares_explicit_timezone_offsets_as_instants():
    source = whole_span_series(rows=2)
    source["metadata"]["experiments"] = []
    for spectrum in source["spectra"]:
        spectrum["metadata"].update({"acquisition_parameters": {},
            "acquisition_start": "2025-01-01T00:00:00+00:00",
            "acquisition_end": "2025-01-01T00:02:00+00:00"})
    second = deepcopy(source["spectra"])
    for spectrum in second:
        spectrum["id"] += "-offset"
        spectrum["metadata"].update({"experiment_source": "recorded-nmr/5",
            "acquisition_start": "2025-01-01T02:00:00+02:00",
            "acquisition_end": "2025-01-01T02:04:00+02:00"})
    source["spectra"] += second
    result = align_same_start(source)
    # Both groups started at the same instant, despite differing clock displays.
    assert [s["time_s"] for s in result["spectra"]] == [0, 60, 0, 120]
    assert [s["duration_s"] for s in result["spectra"]] == [60, 60, 120, 120]


@pytest.mark.parametrize("start,end", [
    ("2025-01-01T00:00:00", "2025-01-01T00:02:00+00:00"),
    ("2025-01-01T00:00:00+00:00", "2025-01-01T00:02:00"),
])
def test_same_start_iso_fallback_rejects_mixed_timezone_awareness(start, end):
    source = whole_span_series(rows=2)
    source["metadata"]["experiments"] = []
    for spectrum in source["spectra"]:
        spectrum["metadata"].update({"acquisition_parameters": {},
            "acquisition_start": start, "acquisition_end": end})
    before = deepcopy(source)
    with pytest.raises(ValueError, match="explicit manual cadence"):
        align_same_start(source)
    assert source == before
