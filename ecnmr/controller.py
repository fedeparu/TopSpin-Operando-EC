"""One acquisition model for offline analysis and progressive recorded replay."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import threading
import time
import numpy as np
from .model import validate
from .synthetic import demo


class Controller:
    def __init__(self, state_dir: Path):
        state_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.closed = False
        self.db = sqlite3.connect(state_dir / "recovery.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS snapshot (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, wall_time REAL, kind TEXT, payload TEXT)")
        self.source = demo()
        self.mode, self.state, self.elapsed_s = "offline", "ready", 0.0
        self.speed, self.error, self.revision = 600.0, None, 0
        self._last = time.monotonic()
        row = self.db.execute("SELECT value FROM snapshot WHERE key='source'").fetchone()
        if row:
            try:
                source = validate(json.loads(row[0]))
                state_row = self.db.execute("SELECT value FROM snapshot WHERE key='state'").fetchone()
                if state_row is None:
                    raise ValueError("Missing recovery state")
                state = json.loads(state_row[0])
                if state["mode"] not in {"offline", "simulation"} or state["state"] not in {"ready", "running", "paused", "completed", "stopped", "error"}:
                    raise ValueError("Unknown recovery mode/state")
                if not np.isfinite(state["elapsed_s"]) or state["elapsed_s"] < 0 or not 0 < state["speed"] <= 100000:
                    raise ValueError("Invalid recovery clock")
                self.source = source
                self.mode, self.elapsed_s, self.speed = state["mode"], state["elapsed_s"], state["speed"]
                self.state = "paused" if state["state"] == "running" else state["state"]
                self.error = "Recovered after interruption; review and resume explicitly" if self.state == "paused" else state.get("error")
            except (ValueError, KeyError, TypeError):
                self.error = "Invalid recovery snapshot; synthetic example loaded"
        self._save_source()
        self._event("open", {"recovered": bool(row)})

    def _write(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO snapshot VALUES (?,?)", (key, json.dumps(value, allow_nan=False)))

    def _save_source(self):
        self._write("source", self.source)
        self._save_state()

    def _save_state(self):
        self._write("state", {"mode": self.mode, "state": self.state, "elapsed_s": self.elapsed_s,
                              "speed": self.speed, "error": self.error})
        self.db.commit()

    def _event(self, kind, payload=None):
        self.db.execute("INSERT INTO events(wall_time,kind,payload) VALUES(?,?,?)",
                        (time.time(), kind, json.dumps(payload or {}, allow_nan=False)))
        self.db.commit()
        self.revision += 1

    def replace(self, source):
        with self.lock:
            if self.state == "running":
                raise ValueError("Stop the simulation before replacing its data")
            self.source = validate(deepcopy(source))
            self.mode, self.state, self.elapsed_s, self.error = "offline", "ready", 0.0, None
            self._save_source()
            self._event("load", {"experiment_id": source["id"]})

    def counts(self):
        if self.mode == "offline":
            return len(self.source["ec"]["time_s"]), len(self.source["spectra"])
        ec_count = int(np.searchsorted(self.source["ec"]["time_s"], self.elapsed_s, side="right"))
        offset = self.source["alignment"]["offset_s"]
        available = sum(s.get("time_s") is not None and s["time_s"] + offset + (s.get("duration_s") or 0) <= self.elapsed_s
                        for s in self.source["spectra"])
        return ec_count, available

    def view(self):
        with self.lock:
            result = deepcopy(self.source)
            if self.mode != "offline":
                ec_count, _ = self.counts()
                for field in ("time_s", "voltage_V", "current_mA", "capacity_mAh"):
                    result["ec"][field] = result["ec"][field][:ec_count]
                for key, values in result["ec"].get("metadata", {}).get("additional_columns", {}).items():
                    # Auxiliary cycle/step/charge columns are measurements too;
                    # a partial session must not expose their future values.
                    if isinstance(values, list) and len(values) == len(self.source["ec"]["time_s"]):
                        result["ec"]["metadata"]["additional_columns"][key] = values[:ec_count]
                offset = result["alignment"]["offset_s"]
                result["spectra"] = [s for s in result["spectra"] if s.get("time_s") is not None and
                                     s["time_s"] + offset + (s.get("duration_s") or 0) <= self.elapsed_s]
            return result

    def status(self):
        with self.lock:
            ec, nmr = self.counts()
            return {"state": self.state, "mode": self.mode, "elapsed_s": self.elapsed_s,
                    "available_ec": ec, "available_spectra": nmr,
                    "total_ec": len(self.source["ec"]["time_s"]), "total_spectra": len(self.source["spectra"]),
                    "event_count": self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                    "error": self.error, "speed": self.speed, "revision": self.revision,
                    "hardware_validated": False}

    def set_mode(self, mode):
        with self.lock:
            if mode == "live":
                raise ValueError("Live hardware acquisition is unavailable: vendor adapters and SP-150e have not been validated")
            if mode not in {"offline", "simulation"}:
                raise ValueError("Unknown operating mode")
            if self.state == "running":
                raise ValueError("Stop or pause the simulation before changing modes")
            self.mode, self.state, self.elapsed_s, self.error = mode, "ready", 0.0, None
            self._save_state()
            self._event("mode", {"mode": mode})
            return self.status()

    def action(self, action, speed=None):
        with self.lock:
            if speed is not None:
                if not np.isfinite(speed) or not 0 < speed <= 100000:
                    raise ValueError("Replay speed must be between 0 and 100000")
                self.speed = float(speed)
            if action in {"prepare", "reset"}:
                if self.state == "running":
                    raise ValueError("Stop the simulation before resetting")
                if self.source["alignment"]["method"] == "unaligned" or any(s.get("time_s") is None for s in self.source["spectra"]):
                    raise ValueError("Align the recorded spectra before replay, or load the synthetic demonstration")
                self.mode, self.state, self.elapsed_s, self.error = "simulation", "ready", 0.0, None
            elif action == "start":
                if self.mode != "simulation" or self.state != "ready":
                    raise ValueError("Prepare simulation before starting")
                if self.source["alignment"]["method"] == "unaligned" or any(s.get("time_s") is None for s in self.source["spectra"]):
                    raise ValueError("Replay requires explicit timing alignment")
                self.state = "running"
                self._last = time.monotonic()
            elif action in {"pause", "disconnect"}:
                if self.state != "running":
                    raise ValueError("Only a running simulation can be paused/disconnected")
                self.state = "paused"
                self.error = "Simulated communication loss; acquisition clock frozen, no missing samples invented" if action == "disconnect" else None
            elif action in {"resume", "reconnect"}:
                if self.state != "paused":
                    raise ValueError("Only a paused simulation can resume")
                self.state, self.error = "running", None
                self._last = time.monotonic()
            elif action == "stop":
                self.state = "stopped"
            elif action == "fail":
                if self.mode != "simulation":
                    raise ValueError("Failure injection is available in simulation only")
                self.state, self.error = "error", "Simulated acquisition failure; existing measurements preserved"
            else:
                raise ValueError("Unknown simulation action")
            self._save_state()
            self._event(action, {"elapsed_s": self.elapsed_s})
            return self.status()

    def advance(self, wall_seconds):
        """Deterministic progression, independent of UI refresh rate."""
        with self.lock:
            if self.closed or self.state != "running":
                return
            previous = self.counts()
            self.elapsed_s += max(0, wall_seconds) * self.speed
            ec_end = max(self.source["ec"]["time_s"], default=0)
            offset = self.source["alignment"]["offset_s"]
            nmr_end = max((s["time_s"] + offset + (s.get("duration_s") or 0) for s in self.source["spectra"]), default=0)
            end = max(ec_end, nmr_end)
            if self.elapsed_s >= end:
                self.elapsed_s, self.state = end, "completed"
                self._event("completed")
            if previous != self.counts():
                self._event("append", {"elapsed_s": self.elapsed_s, "ec_count": self.counts()[0], "nmr_count": self.counts()[1]})
            self._save_state()

    def tick(self):
        # A cancelled asyncio.to_thread await does not stop its worker. The
        # shutdown flag prevents a queued poll from touching a closed database.
        with self.lock:
            if self.closed:
                return
            now = time.monotonic()
            delta, self._last = now - self._last, now
            self.advance(delta)

    def analysis(self, settings):
        with self.lock:
            self.source["analysis"] = settings
            self._save_source()
            self._event("analysis")
            return settings

    def events(self):
        with self.lock:
            return [{"id": row[0], "wall_time": row[1], "kind": row[2], "payload": json.loads(row[3])}
                    for row in self.db.execute("SELECT * FROM events ORDER BY id")]

    def close(self):
        with self.lock:
            if self.closed:
                return
            self._save_state()
            self.closed = True
            self.db.close()
