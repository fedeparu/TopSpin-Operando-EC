"""Conservative discovery of externally completed processed 1D spectra.

File stability alone cannot prove acquisition completion. A writer must create
``ecnmr.complete`` only after acquisition and processing have succeeded. This
helper is an integration building block, not an enabled live hardware workflow.
Never use it for a binary .mpr file while EC-Lab is acquiring.
"""
from pathlib import Path
import re


def _scalar(text: str, name: str) -> int:
    match = re.search(r"^##\$" + re.escape(name) + r"=\s*(-?\d+)\s*$", text, re.M)
    if not match:
        raise ValueError("Missing integer Bruker parameter " + name)
    return int(match.group(1))


class CompletedSpectrumWatcher:
    """Yield processed folders after an explicit completion marker and stability.

    ``stable_polls`` includes the first observation. Changing the spectrum,
    parameters or marker resets the counter. Previously emitted versions are not
    re-emitted, and an updated complete version may be emitted once more.
    """

    def __init__(self, root: str | Path, stable_polls: int = 2):
        if stable_polls < 2:
            raise ValueError("At least two observations are required.")
        self.root = Path(root)
        self.stable_polls = stable_polls
        self._observed: dict[Path, tuple[tuple, int]] = {}
        self._emitted: dict[Path, tuple] = {}

    @staticmethod
    def _signature(folder: Path) -> tuple | None:
        files = [folder / "1r", folder / "procs", folder / "ecnmr.complete"]
        try:
            parameters = files[1].read_text(encoding="latin-1")
            count = _scalar(parameters, "SI")
            dtype = _scalar(parameters, "DTYPP")
            byte_order = _scalar(parameters, "BYTORDP")
            if count <= 0 or dtype not in (0, 2) or byte_order not in (0, 1):
                return None
            expected = count * (4 if dtype == 0 else 8)
            stats = [file.stat() for file in files]
            # 1D Bruker files may be padded to 1024 bytes. Reject truncation and
            # arbitrary extra payload, rather than accidentally reading a 2D file.
            padded = ((expected + 1023) // 1024) * 1024
            if stats[0].st_size not in (expected, padded):
                return None
            # Marker must be written last, not inherited from an earlier run.
            if stats[2].st_mtime_ns < max(s.st_mtime_ns for s in stats[:2]):
                return None
            return tuple((s.st_size, s.st_mtime_ns) for s in stats)
        except (OSError, ValueError):
            return None

    def poll(self) -> list[Path]:
        complete = []
        for spectrum in sorted(self.root.rglob("1r")):
            folder = spectrum.parent
            signature = self._signature(folder)
            if signature is None:
                self._observed.pop(folder, None)
                continue
            previous, count = self._observed.get(folder, (None, 0))
            count = count + 1 if previous == signature else 1
            self._observed[folder] = signature, count
            if count >= self.stable_polls and self._emitted.get(folder) != signature:
                self._emitted[folder] = signature
                complete.append(folder)
        return complete
