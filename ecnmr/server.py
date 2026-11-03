"""Loopback-only local web service; never sends data to an external server."""
from contextlib import asynccontextmanager
import asyncio
from copy import deepcopy
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import stat
import uuid
import zipfile

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import plotly

from .controller import Controller
from .model import experiment, align, match_spectrum, validate
from .synthetic import demo

log = logging.getLogger(__name__)
MAX_UPLOAD = 128 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024


def unpack(archive: Path, destination: Path):
    with zipfile.ZipFile(archive) as z:
        if len(z.infolist()) > 10000 or sum(i.file_size for i in z.infolist()) > MAX_EXPANDED:
            raise ValueError("ZIP exceeds the supported expanded size or file count")
        for item in z.infolist():
            path = PurePosixPath(item.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or ":" in item.filename or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("Unsafe ZIP member path")
        z.extractall(destination)


def load_paths(ec_path=None, nmr_path=None):
    from .importers import load_ec, load_nmr
    ec, spectra, meta, warnings = None, [], {}, []
    if ec_path:
        ec = load_ec(ec_path)
    if nmr_path:
        spectra, meta, warnings = load_nmr(nmr_path)
    exp = experiment(ec, spectra, meta, warnings)
    exp["warnings"].extend(exp["ec"]["metadata"].get("warnings", []))
    exp["name"] = "Imported EC–NMR experiment"
    exp["warnings"].append("Independent recordings: verify clocks and supply explicit alignment; original timestamps are preserved.")
    if spectra:
        exp["analysis"]["selected_ids"] = [spectra[0]["id"]]
    return validate(exp)


def create_app(state_dir=None, initial=None, auto_tick=True):
    root = Path(state_dir or os.environ.get("ECNMR_STATE_DIR", ".ecnmr")).resolve()
    controller = Controller(root)
    if initial:
        controller.replace(initial)

    @asynccontextmanager
    async def lifespan(app):
        async def worker():
            while True:
                await asyncio.sleep(0.25)
                await asyncio.to_thread(controller.tick)
        task = asyncio.create_task(worker()) if auto_tick else None
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        controller.close()

    app = FastAPI(title="EC–NMR", lifespan=lifespan)
    app.state.controller = controller

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        # No cross-origin writes, including cross-site HTML form submissions.
        host = request.headers.get("host", "").split(":")[0]
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "Use the loopback URL"}, status_code=403)
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in {f"http://{request.headers.get('host')}", f"https://{request.headers.get('host')}"}:
            return JSONResponse({"detail": "Cross-origin writes are disabled"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/api/experiment")
    def get_experiment():
        return controller.view()

    @app.get("/api/state")
    def get_state():
        return controller.status()

    @app.get("/api/events")
    def events():
        return controller.events()

    @app.post("/api/mode")
    def mode(body: dict):
        return controller.set_mode(body.get("mode"))

    @app.post("/api/demo")
    def demonstration():
        controller.replace(demo())
        return controller.view()

    async def save_upload(upload, directory):
        suffix = Path(upload.filename or "upload").suffix.lower()
        if suffix not in {".zip", ".mpr", ".mpt", ".json"}:
            raise ValueError("Supported uploads: .zip, .mpr, .mpt, .json")
        # Retain the original filename for provenance, without accepting paths
        # or platform-specific filename control characters from an upload.
        filename = PurePosixPath((upload.filename or "upload").replace("\\", "/")).name
        stem = re.sub(r'[<>:"|?*\x00-\x1f]', "_", Path(filename).stem).strip(" .")[:160] or "upload"
        target = directory / (stem + suffix)
        total = 0
        with target.open("wb") as f:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise ValueError("Upload exceeds 128 MiB limit")
                f.write(chunk)
        if suffix == ".zip":
            dest = directory / "extracted"
            try:
                await asyncio.to_thread(unpack, target, dest)
            except (zipfile.BadZipFile, OSError) as exc:
                raise ValueError(f"Cannot open ZIP archive: {exc}") from exc
            return dest
        return target

    @app.post("/api/import")
    async def import_data(ec_file: UploadFile | None = File(None), nmr_file: UploadFile | None = File(None)):
        if controller.state == "running":
            raise ValueError("Stop simulation before importing")
        if not ec_file and not nmr_file:
            raise ValueError("Choose an electrochemical file and/or a Bruker ZIP")
        directory = root / "imports" / uuid.uuid4().hex
        directory.mkdir(parents=True)
        paths = []
        for kind, upload in (("ec", ec_file), ("nmr", nmr_file)):
            if upload:
                folder = directory / kind
                folder.mkdir()
                paths.append(await save_upload(upload, folder))
            else:
                paths.append(None)
        try:
            source = await asyncio.to_thread(load_paths, *paths)
            source["metadata"]["original_uploads"] = {
                kind: upload.filename for kind, upload in (("ec", ec_file), ("nmr", nmr_file)) if upload
            }
            controller.replace(source)
        except (OSError, KeyError, IndexError, NotImplementedError, zipfile.BadZipFile) as exc:
            log.exception("Import failed")
            raise ValueError(f"Cannot import dataset: {exc}") from exc
        return controller.view()

    @app.post("/api/alignment")
    def alignment(body: dict):
        allowed = {"offset_s", "interval_s", "duration_s", "uncertainty_s", "method"}
        if set(body) - allowed:
            raise ValueError("Unknown alignment setting")
        if any(value is not None and not isinstance(value, (int, float)) for key, value in body.items() if key != "method"):
            raise ValueError("Alignment times must be numbers in seconds")
        if body.get("offset_s", 0) is None:
            raise ValueError("Alignment offset cannot be null")
        controller.replace(align(controller.source, **body))
        return controller.view()

    @app.get("/api/spectrum-match")
    def matching(time_s: float):
        return match_spectrum(controller.view(), time_s)

    @app.post("/api/simulation/{action}")
    def simulation(action: str, body: dict | None = None):
        return controller.action(action, (body or {}).get("speed"))

    @app.put("/api/analysis")
    def analysis(body: dict):
        if len(json.dumps(body)) > 65536:
            raise ValueError("Analysis settings exceed 64 KiB")
        return controller.analysis(body)

    @app.get("/api/session")
    def session():
        # Save exactly the visible measurements, including an interrupted replay.
        result = controller.view()
        result["metadata"]["capture_state"] = controller.status()
        return JSONResponse(result, headers={"Content-Disposition": 'attachment; filename="ecnmr.session.json"'})

    @app.post("/api/session")
    async def restore(file: UploadFile = File(...)):
        raw = await file.read(MAX_UPLOAD + 1)
        if len(raw) > MAX_UPLOAD:
            raise ValueError("Session exceeds 128 MiB")
        try:
            restored = validate(json.loads(raw))
        except (KeyError, TypeError) as exc:
            raise ValueError("Invalid session structure") from exc
        controller.replace(restored)
        return controller.view()

    @app.get("/vendor/plotly.min.js")
    def plotly_bundle():
        return FileResponse(Path(plotly.__file__).parent / "package_data" / "plotly.min.js", media_type="application/javascript")

    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")
    return app
