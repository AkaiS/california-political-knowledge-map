"""Restore the historical experiment dependencies and apply frozen source files."""

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[5]
RUNTIME = REPOSITORY / ".scratch/jev-staged-runtime"
MANIFEST = json.loads((HERE / "source-manifest.json").read_text())


def prepare() -> Path:
    """Verify the tracked snapshot before restoring its runnable dependencies."""
    for name, expected in MANIFEST["files"].items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen experimental source changed: {name}")
    marker = RUNTIME / "source-manifest.json"
    if marker.exists():
        if marker.read_bytes() != (HERE / marker.name).read_bytes():
            raise ValueError("Existing runtime belongs to a different experiment snapshot")
        for name, expected in MANIFEST["files"].items():
            relative = name.removeprefix("overlay/")
            installed = RUNTIME / "src" / relative if name.startswith("overlay/") else RUNTIME / relative
            if hashlib.sha256(installed.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Existing runtime source changed: {relative}")
        return RUNTIME
    if RUNTIME.exists():
        raise FileExistsError("Refusing to overwrite an existing incomplete experiment runtime")
    archive = subprocess.check_output(
        ["git", "archive", MANIFEST["base_commit"], "src",
         "work/initiatives/useful-graph-retrieval/query-construction/verified-results.json"],
        cwd=REPOSITORY,
    )
    RUNTIME.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jev-staged-", dir=RUNTIME.parent) as temporary:
        restored = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(restored, filter="data")
        for name in MANIFEST["files"]:
            relative = name.removeprefix("overlay/")
            destination = restored / "src" / relative if name.startswith("overlay/") else restored / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(HERE / name, destination)
        shutil.copyfile(HERE / marker.name, restored / marker.name)
        restored.rename(RUNTIME)
    return RUNTIME


def activate() -> Path:
    runtime = prepare()
    sys.path[:0] = [str(runtime / "src"), str(runtime)]
    return runtime


if __name__ == "__main__":
    print(prepare())
