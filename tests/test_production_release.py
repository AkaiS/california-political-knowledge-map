from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import production_preflight

SPEC = importlib.util.spec_from_file_location(
    "production_release", SCRIPTS / "production_release.py"
)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)

CANDIDATE = "a" * 40
PREVIOUS = "b" * 40
TOKEN = "private-token-value"
PRIVATE_KEY = "private-key-value\n"


@pytest.fixture
def environment(monkeypatch, tmp_path):
    monkeypatch.setattr(production_preflight.Path, "home", lambda: tmp_path)
    return {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": CANDIDATE,
        "BOTTLE_INSTANCE_HOSTNAME": "zone.example",
        "BOTTLE_APP_NAME": "ca-map",
        "BOTTLE_API_TOKEN": TOKEN,
        "BOTTLE_SSH_PRIVATE_KEY": PRIVATE_KEY,
        "BOTTLE_SSH_KNOWN_HOSTS": "zone.example ssh-ed25519 key\n",
    }


class Zone:
    """A fake production host that records every command it receives."""

    def __init__(self, *, tip=CANDIDATE, running=PREVIOUS, disk="63%", fail=None):
        self.tip, self.running, self.disk, self.fail = tip, running, disk, fail
        self.container_up = True
        self.commands: list[list[str]] = []
        self.stages: list[str] = []

    def label(self, command):
        if command[0] == "git":
            return "git rev-parse" if command[1] == "rev-parse" else "ls-remote"
        if command[0] == "ssh":
            remote = command[-1]
            if remote.startswith("df"):
                return "disk"
            if "inspect" in remote:
                return "inspect"
            assert "update --restart=no openhost-ca-map" in remote
            assert "supervisorctl" in remote
            return "shutdown"
        if command[:2] == ["bottle", "curl"]:
            return "set-remote" if "POST" in command else "apps"
        return command[2]

    def __call__(self, command, **options):
        self.commands.append(command)
        assert not any(name.startswith("BOTTLE_") for name in options["env"])
        assert not any(secret in str(command) for secret in (TOKEN, PRIVATE_KEY))
        label = self.label(command)
        self.stages.append(label)
        if label == self.fail:
            return subprocess.CompletedProcess(command, 1, stdout=TOKEN, stderr="")
        stdout = {
            "git rev-parse": CANDIDATE,
            "ls-remote": f"{self.tip}\trefs/heads/main\n",
            "disk": self.disk,
            "apps": json.dumps(
                [
                    {"app_id": "other1", "name": "other"},
                    {"app_id": "abc123", "name": "ca-map"},
                ]
            ),
            "status": f"ca-map: running\n  git commit: x @ {self.running}\n",
        }.get(label, "")
        if label == "inspect":
            stdout = "true" if self.container_up else "false"
        if label == "shutdown":
            self.container_up = False
        if label == "set-remote":
            body = json.loads(command[command.index("--data") + 1])
            assert body == {"repo_url": f"{release.REPOSITORY_URL}@{CANDIDATE}"}
            assert command[3] == "production"
            assert command[-5].endswith("/set_app_remote/abc123")
        if label == "reload":
            assert command[2:6] == ["reload", "ca-map", "--update", "--wait"]
            assert options["timeout"] == release.RELOAD_SECONDS
            self.running = CANDIDATE
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def run(monkeypatch, environment, zone, ready=lambda url: True):
    monkeypatch.setattr(production_preflight.subprocess, "run", zone)
    progress = release.Progress()
    return progress, lambda: release.release(
        environment, progress, ready=ready, sleep=lambda _: None
    )


def test_approved_candidate_is_shut_down_pinned_reloaded_and_verified(
    monkeypatch, environment, tmp_path
):
    zone = Zone()
    urls = []
    _, go = run(
        monkeypatch, environment, zone, ready=lambda url: urls.append(url) or True
    )
    summary = go()
    assert zone.stages == [
        "git rev-parse",
        "ls-remote",
        "status",
        "disk",
        "apps",
        "inspect",
        "shutdown",
        "inspect",
        "set-remote",
        "reload",
        "status",
    ]
    assert urls == ["https://ca-map.zone.example/health/ready"]
    assert CANDIDATE in summary and PREVIOUS in summary
    assert not (tmp_path / ".cloud_in_a_bottle_cli").exists()


def test_newer_main_commit_refuses_before_reading_credentials(monkeypatch, environment):
    zone = Zone(tip="c" * 40)
    monkeypatch.setattr(
        production_preflight,
        "required",
        lambda *args: pytest.fail("A stale candidate accessed credentials"),
    )
    _, go = run(monkeypatch, environment, zone)
    with pytest.raises(release.PreflightError, match="newer main commit"):
        go()


def test_untrusted_event_runs_nothing(monkeypatch, environment):
    environment["GITHUB_EVENT_NAME"] = "pull_request"
    zone = Zone()
    _, go = run(monkeypatch, environment, zone)
    with pytest.raises(release.PreflightError):
        go()
    assert zone.commands == []


def test_already_released_candidate_is_left_running(monkeypatch, environment):
    zone = Zone(running=CANDIDATE)
    _, go = run(monkeypatch, environment, zone)
    assert "already runs" in go()
    assert zone.stages == ["git rev-parse", "ls-remote", "status"]


def test_full_disk_refuses_before_stopping(monkeypatch, environment):
    zone = Zone(disk="85%")
    progress, go = run(monkeypatch, environment, zone)
    with pytest.raises(release.PreflightError, match="less than 20% free"):
        go()
    assert "shutdown" not in zone.stages
    assert "not changed" in release.failure_summary("x", progress)


def test_failed_rebuild_reports_stopped_app_without_secrets(monkeypatch, environment):
    zone = Zone(fail="reload")
    progress, go = run(monkeypatch, environment, zone)
    with pytest.raises(release.PreflightError) as error:
        go()
    summary = release.failure_summary(str(error.value), progress)
    assert progress.stopped and progress.previous == PREVIOUS
    assert "may be unavailable" in summary and PREVIOUS in summary
    assert TOKEN not in summary


def test_unready_release_fails_after_deadline(monkeypatch, environment):
    zone = Zone()
    monkeypatch.setattr(release, "READY_SECONDS", -1)
    _, go = run(monkeypatch, environment, zone, ready=lambda url: False)
    with pytest.raises(release.PreflightError, match="did not become ready"):
        go()


def test_unexpected_failure_never_prints_secrets_or_traceback(monkeypatch, capsys):
    monkeypatch.setattr(
        release, "release", lambda *_: (_ for _ in ()).throw(RuntimeError(TOKEN))
    )
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert release.main() == 1
    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err
    assert "Traceback" not in output.out + output.err
