# Architecture and implementation boundaries

A single local Python application serves a browser interface and JSON API on
loopback. Plotly assets are served locally; no cloud service or vendor software
is required for Offline and Simulation. UI plots and interaction are shared
between modes.

| Component | Responsibility |
| --- | --- |
| Importers | Read completed EC-Lab exports/binaries and Bruker processed data; retain units, metadata and source references. |
| Experiment model | Keep EC elapsed seconds, NMR spectra, original timestamps, alignment settings, analysis state and warnings together. |
| Alignment | Keep unknown timestamps unknown; expose manual offsets and explicitly supplied series cadence separately from original metadata. |
| Controller | Progressively reveal simulated EC samples and completed spectra, implement workflow state transitions and record events. |
| Browser | Link EC selection to spectra, highlight NMR intervals, overlay spectra and track selected peak regions. |
| Persistence | Save/reopen experiment and analysis state; preserve incremental acquisition state and events locally. |
| Hardware adapters | Fail-closed boundaries. No real SP-150e or spectrometer calls are implemented. |
| Completion watcher | Standalone tested helper requiring a completion marker, valid processed 1D dimensions and repeated stability observations. |
| TopSpin launcher | Site-configurable Jython script starts the external viewer with the current dataset; validation within TopSpin remains necessary. |

Offline import and simulation use one schema. Their shared view does not imply
that unsynchronized source experiments have a common clock. The supplied Bruker
pseudo2D file has no per-row acquisition timestamps; a user-supplied cadence is
an explicit assumption, not recovered experimental evidence. The original
metadata remain available for inspection.

The real-control boundary rejects every start. OLE-COM protocol execution and
continuous numerical data access are separate capabilities and must be verified
separately. Active binary EC-Lab files are not polled. The next validated driver
can append completed data to the existing model without adding another viewer.

See [instrument integration](INSTRUMENT_INTEGRATION.md) for official evidence,
Windows diagnostics, launcher setup and the real-hardware acceptance procedure.
