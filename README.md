# TopSpin Operando EC–NMR prototype

A working **local** application for completed EC–NMR data and simulated live
acquisition. One Plotly interface supports importing, alignment, linked spectral
selection, overlays, peak integration, progressive acquisition, saving and reopening.
The browser, data service and charts run on your computer; no cloud account,
EC-Lab installation or TopSpin installation is needed for these two modes.

**Real hardware acquisition is disabled.** The optional TopSpin launcher is
provided for installation-specific validation. Native GUI embedding, COM/OEM
instrument control and actual instrument synchronization have not been tested.

![Synthetic offline viewer with linked spectra](docs/preview-synthetic.png)

## Install and launch on Windows

Install **64-bit Python 3.12** from python.org, including the Python launcher.
Download this branch / release source ZIP, extract it, open PowerShell in that
folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1
.\scripts\launch_windows.cmd
```

The execution-policy option applies only to that PowerShell process; it does not
change system policy. The assistant creates `.venv`, installs pinned dependencies
and writes `work/installation-diagnostics.json`. It inspects optional vendor
availability without activating COM, installing vendor software or modifying
TopSpin. An optional, explicitly approved launcher-copy step is documented in
[instrument integration](docs/INSTRUMENT_INTEGRATION.md).

Equivalent manual installation:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m ecnmr --open
```

Open **http://127.0.0.1:8765** if the browser does not open automatically.
Keep the terminal open; press Ctrl+C there to shut down. A second launch on the
same port requires stopping the first instance. Python 3.10–3.13 is allowed by
our package; verification used Python 3.12 on Linux. Windows installation and
vendor runtime integration still require testing on Windows.

On Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m ecnmr --open
```

## Use the viewer

1. The initial screen contains a clearly labelled **synthetic** battery example.
   In Offline mode, click an EC curve to select a spectrum; select spectra in the
   list to highlight their acquisition intervals. Select several for overlays.
2. Choose a peak region in ppm to track raw, signed integrated intensity over
   time, voltage or charge. Units are intensity·ppm; no baseline correction or
   quantitative concentration calibration is implied.
3. Import a completed `.mpt`/`.mpr` file or ZIP and a ZIP containing a processed
   Bruker experiment/series. The importer reads `1r` or explicitly identified
   pseudo-2D `2rr`; it preserves processing parameters and original timestamps.
   Raw FID reprocessing and true 2D analysis are outside this release.
4. If timing is unknown, inspect metadata and enter an explicit manual offset,
   assumed repetition interval and optional acquisition duration/uncertainty.
   A manual cadence is recorded as an **assumption**. Without alignment,
   spectra can be inspected but EC clicks do not claim a corresponding spectrum.
5. In Simulation mode, prepare and start. Samples and **completed** spectra appear
   progressively. Change replay speed, pause/resume, stop, or inject a simulated
   disconnection/failure. Select older spectra while the run continues. Replay
   of real recordings requires explicit alignment and is still simulation.
6. Save a session to retain the visible data, provenance, alignment and analysis
   settings. Reopen that JSON session through the interface. CSV and chart-image
   exports support further analysis and reporting.

To open files directly, including through the TopSpin launcher:

```powershell
.\.venv\Scripts\python.exe -m ecnmr --open --ec "D:\Data\run.mpr" --nmr "D:\NMR\sample\4"
```

The server binds only to loopback. Do not expose it through an external proxy;
it is a local single-user scientific tool. Imports and recovery state are stored
in ignored `.ecnmr/`, or a directory selected with `--state-dir`. Original files
are never modified. There is no automatic deletion of imported copies.

## Important findings in the supplied experimental files

Both archives were extracted and inspected in full; **none of their raw files
are included in Git**. See the detailed [data inspection](docs/DATA_INSPECTION.md).

- Bruker: **64 × 4096 ⁷Li spectra** in a pseudo-2D matrix. The separate procno
  999 is extracted row 51, so it is excluded as a duplicate when loading the
  experiment. Processing SF, byte order, tiling and `2**NC_proc` scaling are
  checked against the actual binary values.
- BioLogic: **98,790 EC points** over about 51.9 hours, from `.mpr`. No `.mpt`
  was supplied. Measured current is absent; the displayed interval-average
  current is derived from `dq/dt` and labelled accordingly. Charge is exported
  signed cumulative mAh, not mass-normalized or per-cycle discharge capacity.
- The EC internal date is in **2024**, while the NMR acquisition is in **July
  2025**. The NMR rows have no individual acquisition timestamps, and automatic
  tune/match can change their cadence. **These files cannot establish a measured
  common timeline.** Manual alignment enables exploration but cannot prove the
  two recordings were synchronized.

The repository provides entirely [synthetic example files](examples/README.md)
and a deterministic generator for demonstrations and portable tests.

## Automated verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Optional real-data checks (extracted original archives kept outside the repo):

```powershell
$env:ECNMR_REAL_DATA = "D:\PrivateData\extracted"
.\.venv\Scripts\python.exe -m pytest -q
```

Optional browser acceptance tests:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
$env:ECNMR_BROWSER = "1"
.\.venv\Scripts\python.exe -m pytest tests/test_browser.py -q
```

`ECNMR_CHROMIUM` may point to an existing Chromium executable. See
[verification results](docs/VERIFICATION.md) for actual test runs, screenshots,
limitations and covered acceptance criteria. Direct and optional test dependencies
are pinned in `pyproject.toml`; a full Python-3.12 verification snapshot is in
`requirements-tested-py312.txt`.

## Implementation and integration

The application separates `importers`, `model`, `controller`, `server`, `static`
UI, `adapters`, and `watcher`. Sessions are inspectable JSON. SQLite WAL stores
source snapshots, analysis settings, acquisition progress and timestamped events
incrementally. An interrupted running simulation reopens paused rather than
silently continuing; the operator must explicitly resume it. A downloaded
session includes only measurements visible at the moment it is saved.

The [architecture](docs/ARCHITECTURE.md) and [instrument integration guide](docs/INSTRUMENT_INTEGRATION.md)
explain the verified public vendor capabilities, local TopSpin launcher,
conservative completed-spectrum watcher, and exact hardware validation steps.
The watcher is a separately tested integration building block, not an enabled
hardware acquisition path. It requires an external completion marker.

This source is GPL-3.0-or-later because its MPR reader dependency `galvani` uses
that license. Consult [dependency notices](docs/DEPENDENCIES.md) and `LICENSE`
before redistribution. No proprietary vendor code or eCAT code is included.
