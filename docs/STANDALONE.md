# Browser-only and standalone HTML version

The private interactive playground is available at:
https://operando-ecnmr-playground.fedeparuzzo.chatgpt.site

It includes the supplied recordings and a separate, clearly labelled synthetic
example. The hosted Site is owner-private. Real measurements exist only in the
private generated deployment asset, not in Git source.

Click **Download HTML** in the top bar to save one self-contained HTML file.
Plotly, styling, the shared renderer, the browser controller and the embedded
recordings are included. It makes no external data requests and needs no Python
service after export. Use a current Chrome, Edge, Firefox or Safari browser.

- Offline opens all imported measurements. Missing row times remain unknown;
  the initial peak plot uses acquisition number so it can be explored immediately.
- Simulation automatically loads the labelled synthetic example when the current
  real recording lacks row timing. Click Check / prepare, then Start. Explicitly
  aligned real recordings can also be replayed, retaining their assumed timing.
- Open your experimental data returns to the embedded real recording.
- Overlays, the intensity map, manual alignment, peak tracking, image/CSV exports
  and JSON session save/reopen use the same renderer as the Python application.
- Save analysis downloads current measurements, provenance and settings as JSON.
  Browser storage retains small analysis/alignment preferences when permitted;
  playback progress is tab-local. Save JSON before closing the tab.
- This version reopens JSON sessions. New raw `.mpr`, `.mpt` and Bruker imports
  use the Python application first. Hardware acquisition remains unavailable.

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

An exported real-data HTML contains the complete normalized measurements and
metadata. Keep it in a private directory outside Git. It is not a scrubbed demo.
The provided real-data HTML is about 11.8 MB and preserves all 98,790 EC samples and
all 64 × 4096 NMR intensities; the gzip payload is lossless, not downsampled.

## Verification

The complete updated suite passed 59 tests, including four Chromium workflows.
Five tests specifically cover the standalone exporter/browser: exact embedded
measurement identity, no external asset references, actual chart clicking,
overlays, HTML download/reopening, JSON save/reopen, progressive simulation,
disconnection/reconnection, real-recording availability and unknown uncertainty.
Browser tests observed zero HTTP/HTTPS data requests from the exported HTML.

The cloud-managed Chromium policy rejects file:// navigation. The tests executed
the exact saved HTML bytes in fresh browser documents with `set_content`; they
also downloaded and executed the downloaded bytes again. This verifies the
self-contained document without changing browser policy. Double-click launching
on the user's operating system remains a target-browser check.
