"""Verify rendering against the frozen implementation without evaluation data."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from knowledge_map import prompts

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[5]


def test_synthetic_rendered_inputs_match_frozen_snapshot(tmp_path):
    active = ROOT / ".scratch/jev-staged-runtime-v2"
    frozen = tmp_path / "frozen"
    shutil.copytree(active / "src", frozen / "src", ignore=shutil.ignore_patterns("__pycache__"))
    manifest = json.loads((HERE / "source-manifest.json").read_text())
    for name in manifest["files"]:
        relative = "src/" + name.removeprefix("overlay/") if name.startswith("overlay/") else name
        destination = frozen / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / name, destination)
    script = Path(__file__).with_name("prompt_snapshot.py")
    captured = [subprocess.check_output([sys.executable, str(script), str(runtime)], cwd=tmp_path) for runtime in (frozen, active)]
    assert json.loads(captured[0]) == json.loads(captured[1])


def test_resource_versions_match_manifest_and_load_outside_checkout(monkeypatch, tmp_path):
    manifest = json.loads((HERE / "runtime-v2-manifest.json").read_text())
    monkeypatch.chdir(tmp_path)
    for path, expected in manifest["files"].items():
        if path.startswith("src/knowledge_map/resources/prompts/"):
            name = path.removeprefix("src/knowledge_map/resources/prompts/").removesuffix("/v1.txt")
            assert hashlib.sha256(prompts.load_prompt(name, version=1).encode()).hexdigest() == expected
