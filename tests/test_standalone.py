"""The standalone exporter must bundle assets and preserve original data."""
import base64
import gzip
import json
import os
from pathlib import Path
import re

import pytest

from ecnmr.standalone import build_html
from ecnmr.synthetic import demo


def payload(html):
    match = re.search(r'<script id="ecnmr-payload" type="application/octet-stream">([^<]+)</script>', html)
    assert match
    return json.loads(gzip.decompress(base64.b64decode(match[1])))


def test_single_html_contains_plotting_library_renderer_and_exact_source_data():
    source = demo()
    source["alignment"] = {"method": "unaligned", "offset_s": 0, "uncertainty_s": None}
    for spectrum in source["spectra"]:
        spectrum["time_s"], spectrum["duration_s"] = None, None
    html = build_html(source)
    data = payload(html)
    assert not re.search(r'<script[^>]+src=|<link[^>]+stylesheet', html)
    assert "plotly.js" in html.lower()
    assert "ECNMR_TRANSPORT" in html
    assert data["real"]["ec"] == source["ec"]
    assert data["real"]["spectra"] == source["spectra"]
    assert data["real"]["alignment"]["uncertainty_s"] is None
    assert data["real"]["analysis"]["x_axis"] == "index"
    assert source["analysis"]["x_axis"] == "time"  # Export does not mutate source.
    assert data["demo"]["metadata"]["synthetic"]


def test_synthetic_only_html_is_self_contained_and_does_not_require_private_data():
    data = payload(build_html())
    assert data["real"] is None
    assert len(data["demo"]["spectra"]) == 24


@pytest.mark.real
def test_real_standalone_preserves_all_original_measurements_and_unknown_timing():
    root = os.environ.get("ECNMR_REAL_DATA")
    if not root:
        pytest.skip("Set ECNMR_REAL_DATA to privately extracted original archives")
    from ecnmr.server import load_paths
    root = Path(root)
    source = load_paths(next(root.rglob("*.mpr")), root / "4")
    data = payload(build_html(source))["real"]
    assert len(data["ec"]["time_s"]) == 98790
    assert len(data["spectra"]) == 64
    assert data["spectra"] == source["spectra"]
    assert data["ec"] == source["ec"]
    assert all(s["time_s"] is None for s in data["spectra"])
