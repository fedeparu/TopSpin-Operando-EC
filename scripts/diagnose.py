"""Non-invasive installation report; does not instantiate COM or control equipment."""
import argparse
from datetime import datetime, timezone
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys


def diagnostic_report(ole_progid=None):
    packages = {name: importlib.util.find_spec(name) is not None for name in
                ("fastapi", "uvicorn", "numpy", "nmrglue", "galvani", "plotly")}
    vendor_paths = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(variable)
        if base:
            for relative in ("BioLogic", "Bio-Logic", "EC-Lab", "Bruker"):
                path = Path(base) / relative
                if path.exists():
                    vendor_paths.append(str(path))
    registrations = []
    if sys.platform == "win32":
        import winreg
        # Enumerate descriptive class names only; no Dispatch/GetActiveObject.
        # A detected registration does not prove activation or access rights.
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "", 0, winreg.KEY_READ | view) as key:
                    index = 0
                    while True:
                        try:
                            name = winreg.EnumKey(key, index)
                        except OSError:
                            break
                        index += 1
                        if any(term in name.lower() for term in ("ec-lab", "eclab", "biologic")):
                            registrations.append(name)
            except OSError:
                pass
        if ole_progid:
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ole_progid + "\\CLSID") as key:
                    winreg.QueryValueEx(key, None)
                registrations.append(ole_progid)
            except OSError:
                pass
    vendor_distributions = []
    for distribution in importlib.metadata.distributions():
        name = (distribution.metadata.get("Name") or "").lower().replace("_", "-")
        if name in ("bruker-nmr-api", "ts-remote-api"):
            vendor_distributions.append(name)
    topspin_api = bool(vendor_distributions)
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "python_supported": (3, 10) <= sys.version_info[:2] < (3, 14),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages_available": packages,
        "offline_simulation_dependencies_ready": all(packages.values()),
        "possible_vendor_installation_paths": vendor_paths,
        "ole_registration_candidates": sorted(set(registrations)),
        "ole_access": "NOT TESTED: registration does not prove accessibility; no COM object created",
        "topspin_api_package_detected": topspin_api,
        "topspin_api_distribution_candidates": vendor_distributions,
        "topspin_connection": "NOT TESTED: no connection attempted",
        "hardware_control": "DISABLED: no validated driver implemented",
        "next_steps": [
            "Offline and Simulation do not require vendor software.",
            "For OLE-COM, activate the option inside EC-Lab using the installed vendor manual.",
            "Verify the exact ProgID, EC-Lab/Python bitness and remote-control methods with BioLogic.",
            "Never register a guessed DLL or enable OLE-COM silently.",
            "For TopSpin, use its installed API documentation and validate the supplied launcher.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ole-progid", help="Exact ProgID from the installed vendor documentation")
    args = parser.parse_args()
    report = json.dumps(diagnostic_report(args.ole_progid), indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
