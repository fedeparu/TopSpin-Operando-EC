"""Single-command launcher for terminals and the optional TopSpin script."""
import argparse
import logging
import threading
import webbrowser
from pathlib import Path
import uvicorn
from .server import create_app, load_paths


def main():
    parser = argparse.ArgumentParser(description="Local EC–NMR viewer (offline / simulation)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open default browser")
    parser.add_argument("--ec", type=Path, help="EC-Lab .mpt/.mpr file or containing directory")
    parser.add_argument("--nmr", type=Path, help="Bruker experiment / pdata directory")
    parser.add_argument("--state-dir", type=Path, default=Path(".ecnmr"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    initial = load_paths(args.ec, args.nmr) if args.ec or args.nmr else None
    app = create_app(args.state_dir, initial)
    if args.open:
        threading.Timer(1.5, webbrowser.open, args=(f"http://127.0.0.1:{args.port}",)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
