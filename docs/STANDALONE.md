# Browser-only and standalone HTML version

The interactive playground is available at:
https://operando-ecnmr-playground.fedeparuzzo.chatgpt.site

It includes the supplied recordings and a separate, clearly labelled synthetic
example. The hosted Site is owner-private. Real measurements exist only in the
private generated deployment asset, not in Git source.

## Explore the recordings

The main view puts EC curves and the NMR series on a **shared vertical time
axis**. Move the mouse through either plot to inspect the corresponding time in
both. Click to **pin** an acquisition, inspect its raw 1D spectrum in the detail
view, and use **Unlock** to return to hover inspection.

Switch between **stacked spectra** and **contour/map** views. Adjust the stacked
display gain, choose the time coverage, or show the full recorded ppm range.
These controls change the display while preserving imported intensities. Peak
tracking, overlays, alignment and instrument settings are secondary controls.

The supplied recordings open with the requested **same-start assumption**:
EC and NMR start at elapsed zero, and 64 NMR rows occupy equal estimated
intervals across the 74,397-second NMR acquisition extent. Each estimated
interval is 1,162.453125 s. The interface labels this assumption and retains
unknown timing uncertainty. It preserves the conflicting original dates and
missing row timestamps; this default supports exploration without claiming
measured synchronization. Open advanced alignment to apply better timing data.

Simulation progressively reveals EC points and completed NMR spectra in the
same interface. Prepare, start, pause/resume or stop; simulated communication
loss can be injected and recovered. A synthetic example remains clearly
labelled. Replaying the supplied recordings is simulation as well.

Save analysis downloads the current measurements, provenance, timing assumptions
and settings as JSON. Reopen it later through the interface. Browser storage
retains small preferences when permitted; playback progress is tab-local. Save
JSON before closing the tab. CSV and image exports are also available.

## Download a self-contained HTML

Click **Download HTML** in the top bar. Plotly, styling, the shared renderer, the
browser controller and embedded recordings are included in one file. It makes
no external data requests and needs no Python service after export. Use a
current Chrome, Edge, Firefox or Safari browser.

The browser-only version reopens JSON sessions. Import new raw `.mpr`, `.mpt`
and Bruker data with the Python application first. Hardware acquisition remains
unavailable.

## Generate your own HTML

After installing project dependencies, export the default synthetic example:

```powershell
.\.venv\Scripts\python.exe -m ecnmr.standalone --output work\operando-standalone.html
```

Include private real files:

```powershell
.\.venv\Scripts\python.exe -m ecnmr.standalone --ec "D:\Data\run.mpr" --nmr "D:\NMR\sample\4" --output work\operando-standalone.html
```

Or export a previously saved analysis:

```powershell
.\.venv\Scripts\python.exe -m ecnmr.standalone --session "D:\Data\analysis.json" --output work\operando-standalone.html
```

An exported real-data HTML contains complete normalized measurements and
metadata. Keep it in a private directory outside Git. The supplied recording
preserves all 98,790 EC samples and all 64 × 4096 NMR intensities; its compressed
embedded payload is lossless.

## Verification

See [verification results](VERIFICATION.md) for the current automated test
counts, screenshots and checked browser workflows. Export tests verify embedded
measurement identity and self-contained assets; browser checks cover linked
selection, saved sessions and progressive simulation.

The cloud-managed Chromium policy rejects `file://` navigation. Automated tests
execute exact saved HTML bytes in fresh browser documents with `set_content`
and can execute downloaded bytes again. Double-click launching remains a check
for the target browser and operating system.
