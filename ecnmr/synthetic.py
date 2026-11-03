"""Deterministic synthetic example; no experimental values are bundled."""
import numpy as np
from .model import experiment


def demo():
    t = np.arange(0, 7201, 10, dtype=float)
    v = 3.25 + 0.85 * np.sin(np.pi * t / 7200)
    current = np.where(t < 3600, 0.5, -0.5)
    capacity = np.r_[0, np.cumsum(np.abs(current[1:]) * np.diff(t) / 3600)]
    ec = {"time_s": t.tolist(), "voltage_V": v.tolist(), "current_mA": current.tolist(),
          "capacity_mAh": capacity.tolist(), "source": "SYNTHETIC / deterministic generator",
          "start_time": "2025-01-01T00:00:00+00:00",
          "metadata": {"synthetic": True, "capacity_basis": "cumulative absolute current integral (mAh), not specific capacity"}}
    spectra = []
    ppm = np.linspace(30, -20, 512)
    for i in range(24):
        centre = 3 + 4 * np.sin(i / 24 * np.pi)
        y = (1 + i / 25) * np.exp(-0.5 * ((ppm - centre) / 1.3)**2)
        y += (0.7 - i / 60) * np.exp(-0.5 * ((ppm + 3) / 0.7)**2)
        spectra.append({"id": f"synthetic-{i+1:02}", "label": f"Spectrum {i+1:02}",
                        "time_s": i * 300.0, "duration_s": 240.0, "ppm": ppm.tolist(),
                        "intensity": y.tolist(), "source": "SYNTHETIC / gaussian peaks",
                        "metadata": {"nucleus": "7Li", "synthetic": True, "timing_basis": "known synthetic clock"}})
    exp = experiment(ec, spectra, {"synthetic": True})
    exp["name"] = "Synthetic operando battery · ⁷Li"
    exp["alignment"] = {"method": "synthetic", "offset_s": 0, "uncertainty_s": 0}
    exp["analysis"]["selected_ids"] = [spectra[0]["id"]]
    return exp
