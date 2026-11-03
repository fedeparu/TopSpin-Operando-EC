# Architecture and implementation boundaries

A single local Python application serves a browser interface and JSON API on
loopback. Plotly assets are served locally; no cloud service or vendor software
is required for Offline and Simulation. UI plots and interaction are shared
between modes.

| Component | Responsibility |
| --- | --- |
| Importers | Read completed EC-Lab exports/binaries and Bruker processed data; retain units, metadata and source references. |
| Experiment model | Keep EC elapsed seconds, NMR spectra, original timestamps, alignment settings, analysis state and warnings together. |
| Alignment | Preserve source timestamps and unknown row timing; store the user-authorized same-start/uniform-interval assumption separately, with advanced overrides. |
| Controller | Progressively reveal simulated EC samples and completed spectra, implement workflow state transitions and record events. |
| Browser | Show EC and stacked/contour NMR on a shared vertical timeline; link hover, pin/unlock selection and a dedicated 1D spectrum detail. Keep overlays, peak tracking and alignment in secondary controls. |
| Persistence | Save/reopen experiment and analysis state; preserve incremental acquisition state and events locally. |
| Hardware adapters | Fail-closed boundaries. No real SP-150e or spectrometer calls are implemented. |
| Completion watcher | Standalone tested helper requiring a completion marker, valid processed 1D dimensions and repeated stability observations. |
| TopSpin launcher | Site-configurable Jython script starts the external viewer with the current dataset; validation within TopSpin remains necessary. |

Offline import and simulation use one schema and renderer. The main interaction
is move the mouse to inspect a shared time, click to pin, and unlock to resume
hover inspection. Gain, time coverage and full-ppm controls adjust the series
display; the selected raw 1D spectrum remains available in its detail view.
Advanced alignment, peak analysis and integration settings stay secondary.

For the supplied recordings, the user-authorized default assumes simultaneous
start at EC elapsed zero. The 64 NMR rows span the recorded 74,397 s in estimated
uniform 1,162.453125 s intervals. This is stored as an analysis assumption with
unknown uncertainty, separately from the original metadata. The source files
have no per-row NMR timestamps and conflicting absolute dates; the display does
not turn its assumed intervals into measured synchronization. Advanced controls
can replace the default when better timing evidence is available.

The real-control boundary rejects every start. OLE-COM protocol execution and
continuous numerical data access are separate capabilities and must be verified
separately. Active binary EC-Lab files are not polled. The next validated driver
can append completed data to the existing model without adding another viewer.

See [instrument integration](INSTRUMENT_INTEGRATION.md) for official evidence,
Windows diagnostics, launcher setup and the real-hardware acceptance procedure.
