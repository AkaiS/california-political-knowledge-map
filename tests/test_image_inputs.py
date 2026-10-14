from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import image_inputs


def test_inputs_are_the_build_context_allowlist():
    assert image_inputs.image_inputs() == [
        "Dockerfile",
        ".dockerignore",
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "src",
        "deployment",
        "classifier",
        "classifier/pyproject.toml",
        "classifier/src",
    ]


def test_context_that_is_not_an_allowlist_is_rejected(tmp_path):
    dockerignore = tmp_path / ".dockerignore"
    dockerignore.write_text("tests\n")
    with pytest.raises(image_inputs.ImageInputsError):
        image_inputs.image_inputs(dockerignore)


@pytest.fixture
def repository(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def commit(path):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"{path} {git('rev-list', '--all', '--count')}\n")
        git("add", "-A")
        git("commit", "-qm", path)
        return git("rev-parse", "HEAD")

    git("init", "-q")
    monkeypatch.chdir(tmp_path)
    return commit


@pytest.mark.parametrize(
    ("path", "changed"),
    [
        ("src/knowledge_map/web.py", True),
        ("deployment/supervisord.conf", True),
        ("uv.lock", True),
        (".dockerignore", True),
        (".github/workflows/ci.yml", False),
        ("scripts/production_release.py", False),
        ("tests/test_web.py", False),
        ("docs/cloud-ci-cd.md", False),
        ("work/README.md", False),
    ],
)
def test_only_image_sources_count_as_changes(repository, path, changed):
    base = repository("README.md")
    head = repository(path)
    assert image_inputs.image_changed(base, head) is changed


def test_main_reports_output_and_treats_missing_base_as_changed(repository, capsys):
    base = repository("README.md")
    head = repository("docs/guide.md")
    image_inputs.main(base, head)
    image_inputs.main("0" * 40, head)
    assert capsys.readouterr().out.splitlines() == ["changed=false", "changed=true"]


def test_unknown_commit_fails_instead_of_skipping_release(repository):
    head = repository("README.md")
    with pytest.raises(image_inputs.ImageInputsError):
        image_inputs.image_changed("f" * 40, head)
