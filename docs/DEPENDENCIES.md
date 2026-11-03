# Dependencies and redistribution

The application's license is **GPL-3.0-or-later** (see `LICENSE` and
`pyproject.toml`). This choice accommodates the GPL-3.0-or-later `galvani` reader.
There is no proprietary vendor SDK, DLL, EC-Lab or TopSpin distribution in this
repository. Experimental data ownership is unaffected by the code's license.

Versions below are the direct pins in `pyproject.toml`. License identifications
were checked against the installed wheel metadata and included license files on
3 November 2026; they are not inferred solely from project names.

| Package | Version | Installed license evidence |
| --- | --- | --- |
| FastAPI | 0.115.6 | MIT classifier and `licenses/LICENSE` |
| Uvicorn | 0.34.0 | BSD-3-Clause metadata and `licenses/LICENSE.md` |
| NumPy | 2.2.6 | BSD terms in `LICENSE.txt`; binary wheels also include third-party notices |
| nmrglue | 0.11 | New BSD metadata; three-clause terms in `LICENSE.txt` |
| galvani | 0.5.0 | GPLv3+ metadata and `licenses/LICENSES/GPL-3.0-or-later.txt` |
| Plotly.py / bundled Plotly.js | 5.24.1 | MIT metadata and `LICENSE.txt`; bundled JavaScript retains its notices |
| python-multipart | 0.0.20 | Apache-2.0 license expression and `licenses/LICENSE.txt` |
| pytest (test extra) | 8.3.5 | MIT metadata and `LICENSE` |
| HTTPX (test extra) | 0.28.1 | BSD-3-Clause metadata and `licenses/LICENSE.md` |
| Playwright (test extra) | 1.56.0 | Apache-2.0 license expression and `licenses/LICENSE` |
| setuptools (build tool) | 80.9.0 | Pin used for isolated package builds; install from its official distribution with its own notices |

The source ZIP does not bundle dependencies. Installation downloads the pinned
packages and their transitive dependencies from the configured Python package
index. NumPy/SciPy wheels can contain OpenBLAS and compiler runtime libraries
with additional notices. Do not remove wheel license files or assume every
binary dependency uses the application's license. A future executable installer
that bundles binaries must include all applicable dependency notices and source
obligations; the present assistant creates a local virtual environment instead.

Plotly JavaScript is served from the installed Plotly package by the local
application. No CDN connection is required for viewing plots. Browser automation
requires a separately installed Playwright browser; browser executables are not
included in the source archive.

`requirements-tested-py312.txt` records the development environment's
resolved versions. Python/OS-specific wheel availability can differ; the direct
pins and supported Python range are authoritative in `pyproject.toml`.
