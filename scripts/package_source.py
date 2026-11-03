"""Package committed source and synthetic examples, never local measurements.

Usage: python scripts/package_source.py --output /path/to/ecnmr-source.zip
The archive uses committed HEAD contents, not local sessions or untracked files.
"""
import argparse
from pathlib import Path, PurePosixPath
import subprocess
import zipfile


BLOCKED_DIRECTORIES = {".git", ".venv", "venv", "work", "datasets", "attachments", "output", "sessions", "__pycache__"}
RAW_EXTENSIONS = {".mpr", ".mpt", ".sta", ".mps", ".zip"}
RAW_FILENAMES = {"fid", "ser", "1r", "1i", "2rr", "2ii", "acqus", "acqu2s", "procs", "proc2s"}


def git(root, *arguments):
    return subprocess.check_output(["git", "-C", str(root), *arguments])


def source_entries(root):
    names = git(root, "ls-tree", "-r", "--name-only", "-z", "HEAD").decode().split("\0")
    entries = []
    for name in filter(None, names):
        path = PurePosixPath(name)
        if any(part in BLOCKED_DIRECTORIES for part in path.parts):
            continue
        # Synthetic format fixtures under examples are permissible; experimental
        # format files elsewhere must be deliberately reviewed before packaging.
        if "examples" not in path.parts and (path.suffix.lower() in RAW_EXTENSIONS or path.name in RAW_FILENAMES):
            raise ValueError("Experimental-format file outside examples: " + name)
        if ".." in path.parts or path.is_absolute():
            raise ValueError("Unsafe archive path: " + name)
        entries.append(name)
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    revision = git(root, "rev-parse", "HEAD").decode().strip()
    entries = source_entries(root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in entries:
            content = git(root, "show", "HEAD:" + name)
            archive.writestr("ecnmr/" + name, content)
        archive.writestr("ecnmr/SOURCE_REVISION.txt", revision + "\n")
    print("Packaged " + str(len(entries)) + " source files from " + revision + " to " + str(args.output))


if __name__ == "__main__":
    main()
