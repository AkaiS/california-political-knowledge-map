import subprocess

from knowledge_map.chat_telemetry import code_state


def test_container_revision_without_git(monkeypatch):
    monkeypatch.setenv("BUILD_REVISION", "a" * 40)

    def missing_git(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing_git)
    assert code_state() == ("a" * 40, None)


def test_checkout_revision_precedes_build_metadata(monkeypatch):
    monkeypatch.setenv("BUILD_REVISION", "stale")
    outputs = iter(("b" * 40 + "\n", " M file\n"))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, next(outputs)),
    )
    assert code_state() == ("b" * 40, True)
