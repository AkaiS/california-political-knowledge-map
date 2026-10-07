"""Restore frozen dependencies, then apply the separately recorded review repairs."""

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
RUNTIME = REPOSITORY / ".scratch/jev-staged-runtime-v2"
MANIFEST = json.loads((HERE / "source-manifest.json").read_text())
RUNTIME_MANIFEST = json.loads((HERE / "runtime-v2-manifest.json").read_text())


def prepare() -> Path:
    """Verify the tracked snapshot before restoring its runnable dependencies."""
    for name, expected in MANIFEST["files"].items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen experimental source changed: {name}")
    patch = HERE / "runtime-v2.patch"
    if hashlib.sha256(patch.read_bytes()).hexdigest() != RUNTIME_MANIFEST["patch_sha256"]:
        raise ValueError("The reviewed runtime patch changed")
    marker = RUNTIME / "runtime-v2-manifest.json"
    if marker.exists():
        if marker.read_bytes() != (HERE / marker.name).read_bytes():
            raise ValueError("Existing runtime belongs to a different experiment snapshot")
        for relative, expected in RUNTIME_MANIFEST["files"].items():
            installed = RUNTIME / relative
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
        subprocess.run(
            ["git", "apply", "--unidiff-zero", f"--directory={restored.relative_to(REPOSITORY)}", str(patch)],
            cwd=REPOSITORY,
            check=True,
        )
        for relative, expected in RUNTIME_MANIFEST["files"].items():
            destination = restored / relative
            if relative == "src/knowledge_map/prompts.py" or relative.startswith("src/knowledge_map/resources/"):
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPOSITORY / relative, destination)
            if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Reviewed runtime differs from its manifest: {relative}")
        shutil.copyfile(HERE / "source-manifest.json", restored / "source-manifest.json")
        shutil.copyfile(HERE / marker.name, restored / marker.name)
        restored.rename(RUNTIME)
    return RUNTIME


def activate() -> Path:
    runtime = prepare()
    sys.path[:0] = [str(runtime / "src"), str(runtime)]
    return runtime


if __name__ == "__main__":
    print(prepare())
