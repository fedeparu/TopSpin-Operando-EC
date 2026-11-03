"""Export the existing viewer to one offline HTML file, without a Python server.

Generated HTML may contain private experimental data. Always export outside Git.
The browser adapter shares the renderer; vendor import remains a Python feature.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import gzip
import json
from pathlib import Path

import plotly

from .model import validate
from .synthetic import demo


def build_html(real=None):
    root = Path(__file__).parent / "static"
    html = (root / "index.html").read_text(encoding="utf-8")
    if real is not None:
        real = validate(deepcopy(real))
        real["name"] = "Your experimental EC–NMR data"
        real["analysis"]["x_axis"] = "index" if real["alignment"]["method"] == "unaligned" else "time"
        real["metadata"]["standalone_html"] = True
    payload = {"real": real, "demo": demo()}
    encoded = base64.b64encode(gzip.compress(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(), mtime=0)).decode()
    css = (root / "style.css").read_text(encoding="utf-8")
    plotly_js = (Path(plotly.__file__).parent / "package_data" / "plotly.min.js").read_text(encoding="utf-8")
    adapter = (root / "standalone.js").read_text(encoding="utf-8")
    app = (root / "app.js").read_text(encoding="utf-8")
    def script(text):
        return "<script>\n" + text.replace("</script", "<\\/script") + "\n</script>"
    html = html.replace('<link rel="stylesheet" href="/static/style.css">', "<style>" + css + "\n.standalone-help{margin:18px 32px 0;padding:14px 18px;border:1px solid #ccded3;background:#eff7f0;border-radius:10px;font-size:12px;line-height:1.6;color:#315d48}.standalone-help strong{font-weight:600}.header-actions{flex-wrap:wrap}@media(max-width:700px){.standalone-help{margin:12px}}</style>")
    html = html.replace('<script src="/vendor/plotly.min.js" defer></script>', script(plotly_js))
    html = html.replace('<script src="/static/app.js" defer></script>',
                        '<script id="ecnmr-payload" type="application/octet-stream">' + encoded + '</script>\n' + script(adapter) + "\n" + script(app))
    html = html.replace('<a class="brand" href="/"', '<a class="brand" href="#"')
    html = html.replace('Local workspace<span class="header-divider">/</span>Prototype', 'Browser workspace<span class="header-divider">/</span>Standalone HTML')
    html = html.replace('<div class="header-actions">', '<div class="header-actions"><button class="button secondary" id="download-html" data-testid="download-html">↓ Download HTML</button>')
    html = html.replace('<main class="app-shell">', '<div class="standalone-help" id="standalone-help"><strong>Ready to explore — no installation needed.</strong> Your recordings open in Offline analysis. Use the spectrum list, overlays, peak controls and intensity map. Choose <strong>Simulation → Check / prepare → Start</strong> to try progressively arriving synthetic data. Real row timing is unknown; manual alignment is an explicit assumption. Download this HTML to use offline; Save analysis keeps your current data and settings in JSON.</div><main class="app-shell">')
    html = html.replace('<button class="button subtle full-width" id="demo-button"', '<button class="button secondary full-width" id="real-button" data-testid="real-button">Open your experimental data</button><button class="button subtle full-width" id="demo-button"')
    html = html.replace('Recorded data are replayed. New spectra appear only after their acquisition ends.', 'Simulation uses the clearly labelled synthetic example when real row timing is unknown. Completed spectra appear progressively.')
    html = html.replace('Raw files remain unchanged.', 'Data stay in this browser. Save JSON before closing. Raw-file import uses the Python app.')
    html = html.replace('Offline import · shared analysis · simulated acquisition', 'Standalone HTML · no server · hardware disabled')
    html = html.replace('Operando · EC–NMR workspace', 'Operando · interactive EC–NMR HTML')
    return html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ec", type=Path)
    parser.add_argument("--nmr", type=Path)
    parser.add_argument("--session", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.session and (args.ec or args.nmr):
        parser.error("Choose --session or --ec/--nmr")
    if args.session:
        real = validate(json.loads(args.session.read_text(encoding="utf-8")))
    elif args.ec or args.nmr:
        from .server import load_paths
        real = load_paths(args.ec, args.nmr)
    else:
        real = None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_html(real), encoding="utf-8")
    print(f"Standalone HTML written: {args.output} ({args.output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
