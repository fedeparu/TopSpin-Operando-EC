"""The same HTTP routes drive analysis, progressive replay and saved sessions."""
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from ecnmr.server import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, auto_tick=False)
    with TestClient(app) as client:
        yield client


def test_loopback_ui_and_plotly_are_local(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    bundle = client.get("/vendor/plotly.min.js")
    assert bundle.status_code == 200
    assert "plotly" in bundle.text[:200].lower()
    assert client.get("/api/state", headers={"host": "external.example"}).status_code == 403
    assert client.post("/api/demo", headers={"origin": "https://external.example"}).status_code == 403


def test_offline_save_close_reopen_restores_data_and_analysis(tmp_path):
    settings = {"selected_ids": ["synthetic-02", "synthetic-05"], "peak_min": 1, "peak_max": 8, "x_axis": "voltage"}
    with TestClient(create_app(tmp_path / "first", auto_tick=False)) as original:
        assert original.put("/api/analysis", json=settings).status_code == 200
        before = original.get("/api/experiment").json()
        saved = original.get("/api/session")
        assert "attachment" in saved.headers["content-disposition"]
    with TestClient(create_app(tmp_path / "second", auto_tick=False)) as reopened:
        response = reopened.post("/api/session", files={"file": ("analysis.json", saved.content, "application/json")})
        assert response.status_code == 200
        after = reopened.get("/api/experiment").json()
        assert after["ec"] == before["ec"]
        assert after["spectra"] == before["spectra"]
        assert after["alignment"] == before["alignment"]
        assert after["analysis"] == settings
        assert reopened.get("/api/spectrum-match", params={"time_s": 420}).json()["spectrum_id"] == "synthetic-02"


def test_simulation_routes_and_partial_session_include_only_arrived_data(client):
    assert client.post("/api/simulation/prepare", json={"speed": 1}).status_code == 200
    assert client.post("/api/simulation/start", json={}).json()["state"] == "running"
    client.app.state.controller.advance(240)
    assert client.get("/api/state").json()["available_spectra"] == 1
    partial = client.get("/api/session").json()
    assert len(partial["spectra"]) == 1
    assert len(partial["ec"]["time_s"]) == 25
    assert client.post("/api/demo").status_code == 400
    assert client.post("/api/mode", json={"mode": "offline"}).status_code == 400
    assert client.post("/api/simulation/disconnect").json()["state"] == "paused"
    assert client.post("/api/simulation/reconnect").json()["state"] == "running"
    assert client.post("/api/simulation/stop").json()["state"] == "stopped"
    assert client.post("/api/mode", json={"mode": "offline"}).json()["available_spectra"] == 24
    assert client.post("/api/mode", json={"mode": "live"}).status_code == 400


@pytest.mark.parametrize("payload", [[], None, {}, {"schema_version": 1}, {"schema_version": 44}])
def test_malformed_session_is_a_reviewable_error(client, payload):
    response = client.post("/api/session", files={"file": ("bad.json", json.dumps(payload), "application/json")})
    assert response.status_code == 400
    assert response.json()["detail"]


@pytest.mark.parametrize("payload", [{"extra": 1}, {"offset_s": None}, {"interval_s": "300"}, {"duration_s": -1}])
def test_invalid_alignment_does_not_replace_existing_data(client, payload):
    before = client.get("/api/experiment").json()
    assert client.post("/api/alignment", json=payload).status_code == 400
    assert client.get("/api/experiment").json() == before


def test_invalid_archives_and_path_traversal_are_rejected(client, tmp_path):
    broken = client.post("/api/import", files={"nmr_file": ("bad.zip", b"not a zip", "application/zip")})
    assert broken.status_code == 400
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../../escape.txt", "should never be extracted")
    response = client.post("/api/import", files={"nmr_file": ("unsafe.zip", stream.getvalue(), "application/zip")})
    assert response.status_code == 400
    assert "Unsafe ZIP" in response.json()["detail"]
    assert not (tmp_path / "escape.txt").exists()


def test_ec_mpt_import_and_missing_units_fail_without_touching_sources(client):
    export = "EC-Lab ASCII FILE\nNb header lines : 3\ntime/s\tEwe/V\tI/mA\n0\t3.1\t1\n10\t3.2\t1\n"
    response = client.post("/api/import", files={"ec_file": ("example.mpt", export.encode(), "text/plain")})
    assert response.status_code == 200, response.text
    exp = response.json()
    assert exp["ec"]["time_s"] == [0, 10]
    assert exp["ec"]["voltage_V"] == [3.1, 3.2]
    assert exp["ec"]["current_mA"] == [1, 1]
    assert exp["ec"]["source"].endswith("example.mpt")
    assert exp["metadata"]["original_uploads"]["ec"] == "example.mpt"
    assert exp["alignment"]["method"] == "unaligned"
    assert client.get("/api/spectrum-match", params={"time_s": 5}).json()["spectrum_id"] is None
    bad = export.replace("time/s", "time")
    assert client.post("/api/import", files={"ec_file": ("bad.mpt", bad.encode(), "text/plain")}).status_code == 400
    assert client.get("/api/experiment").json() == exp


def test_same_start_route_preserves_imported_timing_and_rejects_mixed_arguments(client):
    before = client.get("/api/experiment").json()
    response = client.post("/api/alignment", json={"method": "same_start"})
    assert response.status_code == 200
    same = response.json()
    assert same["alignment"]["assumption"] == "same_start"
    assert same["alignment"]["method"] == "manual"
    assert [s["time_s"] for s in same["spectra"]] == [s["time_s"] for s in before["spectra"]]
    assert client.post("/api/alignment", json={"method": "same_start", "interval_s": 10}).status_code == 400


def test_combined_load_defaults_to_user_authorized_same_start(monkeypatch):
    from ecnmr import importers
    from ecnmr.server import load_paths
    from test_core import whole_span_series
    source = whole_span_series()
    monkeypatch.setattr(importers, "load_ec", lambda path: source["ec"])
    monkeypatch.setattr(importers, "load_nmr", lambda path: (source["spectra"], source["metadata"], []))
    result = load_paths("completed.mpr", "nmr")
    assert result["alignment"]["assumption"] == "same_start"
    assert result["spectra"][1]["time_s"] == 1162.453125
    assert source["spectra"][1]["time_s"] is None
    assert any("assumption" in warning for warning in result["warnings"])
