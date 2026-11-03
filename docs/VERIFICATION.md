# Verification and implementation status

Verified on **3 November 2026**, Debian Linux, Python 3.12.14, with the dependencies
recorded in `requirements-tested-py312.txt`. This is a functional local prototype,
not a validated instrument-control product.

## Implemented and tested

| Capability | Verification |
| --- | --- |
| Real EC import | Supplied completed MPR: 98,790 points; units, potential, charge and reconstructed interval-average current checked. MPT decimal commas, unit conversion and malformed/incomplete data tested with synthetic files. |
| Real NMR import | Supplied 64×4096 pseudo-2D array checked against complete binary values, processing scaling, ppm axis and extracted row51 identity; synthetic 1D, endian and tiled-matrix fixtures also tested. |
| Traceable alignment | Unknown row times retained as null, unaligned EC selection returns no match; explicit operator cadence/offset/duration recorded as assumptions. Interval boundaries, gaps, uncertainty and out-of-range selection tested. |
| Shared offline/simulation model | Both workflows use the same JSON model and browser renderer. Synthetic and recorded replay remain explicitly labelled. |
| Linked browser analysis | Actual Chromium mouse click on rendered EC trace selects spectrum; list selection highlights its acquisition interval; multiple spectral overlays work. |
| Peak analysis | Signed raw integral uses interpolated region boundaries and ascending ppm integration; no implicit normalization or baseline correction. UI also supports peak intensity and EC/charge coordinates. |
| Progressive simulation | Deterministic clock checks and actual running service/browser show EC points and completed spectra arriving separately; no future spectra or auxiliary EC measurements are exposed. |
| Interrupted acquisition | Simulated disconnect freezes the replay clock; reconnect resumes explicitly, failure preserves acquired data, stop prevents further appends. Existing selection and plot zoom survive new completed spectra. |
| Save/reopen | API closes and reopens complete experiment/analysis; browser downloads and reopens selected overlays; real 17.9 MB session round-trip retains all data and metadata. |
| Crash recovery | SQLite WAL snapshots/events/progress are committed incrementally; a running replay reopens paused and requires explicit resume. Corrupt snapshot fallback and late shutdown poll are tested. |
| Local application | Actual uvicorn launch and Chromium rendering, locally served Plotly, static assets, useful import errors and loopback/cross-origin boundaries tested. |
| Packaging | Fresh isolated environment installation, editable package and wheel build inspected; wheel contains all application modules, static assets and license, with no raw data. Source ZIP is built from committed files only. |
| Installation helpers | Python diagnostics executed on Linux; Windows registry absence handled. TopSpin path helper tested. Installer/TopSpin runtime require target-system validation. |

The automated source suite, including opt-in checks against the original data,
passed **52 tests** in 3.62 seconds. Both Chromium acceptance workflows passed
(**2 tests**, 50.48 seconds): synthetic offline/simulation and real import with
explicitly assumed alignment. The browser regression also verifies unknown real
timing uncertainty remains null after applying a manual cadence.

Third-party deprecation warnings arise from Starlette/AnyIO and nmrglue's unused
Tecmag dtype definitions under NumPy2. They did not prevent the tested workflows.

## Reproduce

```sh
# With original ZIPs extracted to a PRIVATE directory outside the repository:
ECNMR_REAL_DATA=/private/extracted .venv/bin/python -m pytest -q --ignore=tests/test_browser.py

# Install Playwright Chromium, or point ECNMR_CHROMIUM at a local browser:
.venv/bin/python -m playwright install chromium
ECNMR_BROWSER=1 ECNMR_REAL_DATA=/private/extracted \
  .venv/bin/python -m pytest tests/test_browser.py -q
```

PowerShell uses `$env:ECNMR_BROWSER = '1'` and
`$env:ECNMR_REAL_DATA = 'D:\PrivateData\extracted'` before the same Python commands.
Without either optional environment variable, those tests skip cleanly.
`ECNMR_SCREENSHOTS` may select a private output directory for screenshots. Keep
real-data screenshots and saved sessions outside Git. In a restricted execution
sandbox, even in-process TestClient needs permission for local asyncio sockets;
browser tests additionally need permission to bind a local server port.

The initial browser run caught real Plotly clipping and shared-axis-title bugs.
Both were fixed and checked visually on desktop and a 390-pixel mobile viewport.
The repository [screenshot](preview-synthetic.png) contains synthetic data only.
Real-data screenshots were generated separately and were not committed.

## Hardware-dependent and unverified

- No real SP-150e, EC-Lab COM/OEM or TopSpin acquisition was connected or started.
  Hardware adapters fail closed; the Live tab explains this boundary.
- The Windows PowerShell assistant, COM registration inspection and TopSpin
  Jython launcher have not run on their target platforms here. Windows CI is
  provided; its remote outcome must be checked separately from local results.
- Native TopSpin GUI embedding is not implemented. The supplied launcher starts
  the external local browser viewer and passes the current dataset.
- The completed-spectrum watcher is a tested helper only. It requires an explicit
  producer completion marker; no vendor-side writer or processing loop is enabled.
- Live numerical EC retrieval, SP-150e board/firmware compatibility, protocol
  start/stop, vendor error handling, processing completion, physical trigger
  wiring and measured cross-instrument synchronization remain to validate.
- Real dataset dates conflict and NMR row times are missing. A manually assumed
  timeline enables linked exploration but never demonstrates measured synchronization.

Follow the concrete [instrument acceptance procedure](INSTRUMENT_INTEGRATION.md)
with the supported vendor APIs, approved dummy-cell protocol, recorded software
versions and independently validated hardware limits before enabling real control.

## Standalone HTML follow-up

The updated complete suite passed **59 tests** in 79.85 seconds, including four
Chromium workflows. The HTML exporter preserves all real samples losslessly and
bundles every plotting asset. Tests execute exported and downloaded HTML bytes
with no backend or external data requests. See [standalone verification](STANDALONE.md)
for exact coverage and the managed browser's file:// policy limitation.
