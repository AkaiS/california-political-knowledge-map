from __future__ import annotations

import importlib.util
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "production_preflight",
    Path(__file__).parents[1] / "scripts/production_preflight.py",
)
assert SPEC is not None and SPEC.loader is not None
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)

CANDIDATE = "a" * 40
CURRENT = "b" * 40
TOKEN = 'private-token-"quoted"\\value'
PRIVATE_KEY = "private-key-value\n"
HOSTS = "zone.example ssh-ed25519 pinned-host-key\n"


@pytest.fixture
def environment():
    return {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": CANDIDATE,
        "BOTTLE_INSTANCE_HOSTNAME": "zone.example",
        "BOTTLE_APP_NAME": "ca-map",
        "BOTTLE_API_TOKEN": TOKEN,
        "BOTTLE_SSH_PRIVATE_KEY": PRIVATE_KEY,
        "BOTTLE_SSH_KNOWN_HOSTS": HOSTS,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"GITHUB_EVENT_NAME": "pull_request"},
        {"GITHUB_EVENT_NAME": "workflow_dispatch"},
        {"GITHUB_REF": "refs/heads/other"},
        {"GITHUB_SHA": "main"},
    ],
)
def test_untrusted_context_never_accesses_credentials_or_runs_commands(
    monkeypatch, environment, change
):
    environment.update(change)

    def unexpected(*args, **kwargs):
        pytest.fail("Untrusted context accessed credentials or ran a command")

    monkeypatch.setattr(preflight, "required", unexpected)
    monkeypatch.setattr(preflight.subprocess, "run", unexpected)
    with pytest.raises(preflight.PreflightError):
        preflight.preflight(environment)


def test_checkout_mismatch_never_accesses_credentials(monkeypatch, environment):
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=CURRENT),
    )
    monkeypatch.setattr(
        preflight,
        "required",
        lambda *args: pytest.fail("Mismatched checkout accessed credentials"),
    )
    with pytest.raises(preflight.PreflightError, match="checkout does not match"):
        preflight.preflight(environment)


@pytest.mark.parametrize("failure", [None, "bottle", "ssh", "timeout"])
def test_credentials_permissions_cleanup_and_read_only_commands(
    monkeypatch, tmp_path, environment, failure
):
    monkeypatch.setattr(preflight.Path, "home", lambda: tmp_path)
    config_path = tmp_path / ".cloud_in_a_bottle_cli/compute_space_cli.toml"
    credential_paths = []
    commands = []

    def run(command, **options):
        commands.append(command)
        assert not any(name.startswith("BOTTLE_") for name in options["env"])
        if command[0] == "git":
            return subprocess.CompletedProcess(command, 0, stdout=CANDIDATE)
        assert options["capture_output"]
        assert options["timeout"] == 45
        assert not any(name.startswith("BOTTLE_") for name in options["env"])
        assert "HOME" not in options["env"]
        assert not any(secret in str(command) for secret in (TOKEN, PRIVATE_KEY, HOSTS))
        config = tomllib.loads(config_path.read_text())
        assert config["default_instance"] == "production"
        instance = config["instances"]["zone.example"]
        assert instance["token"] == TOKEN
        assert instance["alias"] == "production"
        key = Path(instance["ssh_key"])
        hosts = key.parent / "known_hosts"
        credential_paths.extend([key, hosts])
        assert key.read_text() == PRIVATE_KEY
        assert hosts.read_text() == HOSTS
        for path in [config_path, key, hosts]:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in [config_path.parent, key.parent]:
            assert stat.S_IMODE(path.stat().st_mode) == 0o700
        if command[0] == "bottle":
            assert command == [
                "bottle",
                "app",
                "status",
                "ca-map",
                "--instance",
                "production",
            ]
        else:
            assert command[0] == "ssh"
            assert command[-2:] == ["host@zone.example", "true"]
            assert "StrictHostKeyChecking=yes" in command
            assert f"UserKnownHostsFile={hosts}" in command
            assert "GlobalKnownHostsFile=/dev/null" in command
            assert "BatchMode=yes" in command
            assert "IdentitiesOnly=yes" in command
            assert command[1:3] == ["-F", "/dev/null"]
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 45, output=TOKEN)
        code = int(command[0] == failure)
        output = f"ca-map: running\n  git commit: main @ {CURRENT}\n{TOKEN}\n"
        return subprocess.CompletedProcess(
            command, code, stdout=output, stderr=PRIVATE_KEY
        )

    monkeypatch.setattr(preflight.subprocess, "run", run)
    if failure:
        with pytest.raises(preflight.PreflightError) as caught:
            preflight.preflight(environment)
        assert TOKEN not in str(caught.value)
        assert PRIVATE_KEY not in str(caught.value)
        if failure != "ssh":
            assert all(command[0] != "ssh" for command in commands)
    else:
        summary = preflight.preflight(environment)
        assert CANDIDATE in summary and CURRENT in summary
        assert TOKEN not in summary
        assert "No application was deployed" in summary
    assert not config_path.parent.exists()
    assert credential_paths and all(not path.exists() for path in credential_paths)


def test_existing_bottle_configuration_is_never_replaced(
    monkeypatch, tmp_path, environment
):
    monkeypatch.setattr(preflight.Path, "home", lambda: tmp_path)
    directory = tmp_path / ".cloud_in_a_bottle_cli"
    directory.mkdir()
    existing = directory / "compute_space_cli.toml"
    existing.write_text("existing owner credentials")
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=CANDIDATE
        ),
    )
    with pytest.raises(preflight.PreflightError, match="existing Bottle configuration"):
        preflight.preflight(environment)
    assert existing.read_text() == "existing owner credentials"


@pytest.mark.parametrize(
    "hostname", ["https://zone.example", "-oProxyCommand=bad", "zone.example/path"]
)
def test_invalid_target_never_creates_config(
    monkeypatch, tmp_path, environment, hostname
):
    monkeypatch.setattr(preflight.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(preflight, "trusted_revision", lambda _: CANDIDATE)
    environment["BOTTLE_INSTANCE_HOSTNAME"] = hostname
    with pytest.raises(preflight.PreflightError, match="bare DNS hostname"):
        preflight.preflight(environment)
    assert not (tmp_path / ".cloud_in_a_bottle_cli").exists()


def test_unexpected_failure_never_prints_secrets_or_traceback(monkeypatch, capsys):
    monkeypatch.setattr(
        preflight,
        "preflight",
        lambda _: (_ for _ in ()).throw(RuntimeError(TOKEN)),
    )
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert preflight.main() == 1
    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err
    assert "Traceback" not in output.out + output.err
    assert "No application was deployed" in output.out
