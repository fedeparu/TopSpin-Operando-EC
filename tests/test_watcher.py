import os
from ecnmr.watcher import CompletedSpectrumWatcher


def create_processed(root, data=b"\0" * 32, marker=True):
    folder = root / "sample" / "1" / "pdata" / "1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "procs").write_text("##$SI= 8\n##$DTYPP= 0\n##$BYTORDP= 0\n")
    (folder / "1r").write_bytes(data)
    if marker:
        (folder / "ecnmr.complete").write_text("processing successful\n")
    return folder


def test_complete_requires_stability_and_is_not_duplicated(tmp_path):
    folder = create_processed(tmp_path)
    watcher = CompletedSpectrumWatcher(tmp_path)
    assert watcher.poll() == []
    assert watcher.poll() == [folder]
    assert watcher.poll() == []


def test_missing_marker_and_partial_spectrum_never_emitted(tmp_path):
    folder = create_processed(tmp_path, data=b"\0" * 4, marker=False)
    watcher = CompletedSpectrumWatcher(tmp_path)
    assert watcher.poll() == watcher.poll() == []
    (folder / "ecnmr.complete").write_text("done")
    assert watcher.poll() == watcher.poll() == []
    (folder / "1r").write_bytes(b"\0" * 32)
    (folder / "ecnmr.complete").write_text("done")
    assert watcher.poll() == []
    assert watcher.poll() == [folder]


def test_changing_files_resets_stability_and_stale_marker_rejected(tmp_path):
    folder = create_processed(tmp_path)
    watcher = CompletedSpectrumWatcher(tmp_path)
    assert watcher.poll() == []
    (folder / "1r").write_bytes(b"\1" * 32)
    stat = (folder / "1r").stat()
    os.utime(folder / "ecnmr.complete", ns=(stat.st_mtime_ns - 10000, stat.st_mtime_ns - 10000))
    assert watcher.poll() == watcher.poll() == []
    (folder / "ecnmr.complete").write_text("new version complete")
    assert watcher.poll() == []
    assert watcher.poll() == [folder]


def test_invalid_parameters_rejected(tmp_path):
    folder = create_processed(tmp_path)
    (folder / "procs").write_text("##$SI= -1\n##$DTYPP= 9\n##$BYTORDP= 0\n")
    (folder / "ecnmr.complete").write_text("done")
    watcher = CompletedSpectrumWatcher(tmp_path)
    assert watcher.poll() == watcher.poll() == []
