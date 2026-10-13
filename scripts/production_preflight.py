"""Validate production credentials without changing the application or host."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path


class PreflightError(Exception):
    """A failure whose message contains no credential or remote response."""


def subprocess_environment(environment: Mapping[str, str]) -> dict[str, str]:
    return {
        name: environment[name]
        for name in environment
        if not name.startswith("BOTTLE_")
    }


def trusted_revision(environment: Mapping[str, str]) -> str:
    if (
        environment.get("GITHUB_EVENT_NAME") != "push"
        or environment.get("GITHUB_REF") != "refs/heads/main"
    ):
        raise PreflightError("Preflight requires a push to main.")
    revision = environment.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise PreflightError("The candidate revision is missing or invalid.")
    try:
        checkout = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            env=subprocess_environment(environment),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise PreflightError("Cannot verify the checked-out revision.") from None
    if checkout != revision:
        raise PreflightError("The checkout does not match the candidate revision.")
    return revision


def required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not value.strip():
        raise PreflightError(f"Required configuration {name} is missing.")
    return value


def private_file(path: Path, content: str) -> None:
    # Exclusive creation avoids following a pre-existing credential-file symlink.
    with open(
        path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)
    ) as file:
        file.write(content)


def run_read_only(command: list[str], environment: dict[str, str], label: str) -> str:
    try:
        result = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise PreflightError(f"{label} could not complete.") from None
    if result.returncode:
        # Bottle can print HTTP response bodies and SSH can print server banners.
        raise PreflightError(f"{label} failed; remote output is withheld.")
    return result.stdout


def preflight(environment: Mapping[str, str]) -> str:
    revision = trusted_revision(environment)
    hostname = required(environment, "BOTTLE_INSTANCE_HOSTNAME")
    if len(hostname) > 253 or not re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
        hostname,
    ):
        raise PreflightError("BOTTLE_INSTANCE_HOSTNAME must be a bare DNS hostname.")
    app_name = required(environment, "BOTTLE_APP_NAME")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", app_name):
        raise PreflightError("BOTTLE_APP_NAME must be an application name.")
    token = required(environment, "BOTTLE_API_TOKEN")
    ssh_key = required(environment, "BOTTLE_SSH_PRIVATE_KEY")
    known_hosts = required(environment, "BOTTLE_SSH_KNOWN_HOSTS")

    # The pinned CLI reads only this home-directory config path. Refuse an
    # existing directory, so even a local invocation cannot replace credentials.
    config_directory = Path.home() / ".cloud_in_a_bottle_cli"
    config_path = config_directory / "compute_space_cli.toml"
    with tempfile.TemporaryDirectory(prefix="ca-map-preflight-") as temporary:
        credential_directory = Path(temporary)
        key_path = credential_directory / "identity"
        known_hosts_path = credential_directory / "known_hosts"
        private_file(key_path, ssh_key.rstrip("\n") + "\n")
        private_file(known_hosts_path, known_hosts.rstrip("\n") + "\n")
        config = (
            'default_instance = "production"\n'
            f"[instances.{json.dumps(hostname)}]\n"
            f"token = {json.dumps(token)}\n"
            'alias = "production"\n'
            f"ssh_key = {json.dumps(str(key_path))}\n"
        )
        child_environment = subprocess_environment(environment)
        try:
            config_directory.mkdir(mode=0o700)
        except FileExistsError:
            raise PreflightError(
                "An existing Bottle configuration prevents preflight."
            ) from None
        try:
            private_file(config_path, config)
            output = run_read_only(
                ["bottle", "app", "status", app_name, "--instance", "production"],
                child_environment,
                "Bottle application status",
            )
            run_read_only(
                [
                    "ssh",
                    "-F",
                    "/dev/null",
                    "-i",
                    str(key_path),
                    "-o",
                    "IdentitiesOnly=yes",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    f"UserKnownHostsFile={known_hosts_path}",
                    "-o",
                    "GlobalKnownHostsFile=/dev/null",
                    "-o",
                    "ConnectTimeout=15",
                    "-o",
                    "ConnectionAttempts=1",
                    "-o",
                    "ClearAllForwardings=yes",
                    "-o",
                    "ForwardAgent=no",
                    "-o",
                    "PasswordAuthentication=no",
                    "-o",
                    "KbdInteractiveAuthentication=no",
                    "-o",
                    "PermitLocalCommand=no",
                    f"host@{hostname}",
                    "true",
                ],
                child_environment,
                "SSH authentication",
            )
        finally:
            config_path.unlink(missing_ok=True)
            config_directory.rmdir()

    # Report only the CLI's immutable commit field, never arbitrary remote text.
    observed = re.search(
        r"^  git commit: [^\n]+ @ ([0-9a-f]{40})(?: \(dirty\))?$", output, re.MULTILINE
    )
    observed_revision = observed.group(1) if observed else "unavailable"
    return (
        "Production authentication preflight passed.\n\n"
        f"Candidate checkout SHA: `{revision}`.\n\n"
        f"Observed current Bottle checkout SHA: `{observed_revision}`.\n\n"
        "Bottle application status and SSH authentication succeeded. "
        "The SSH command was `true`.\n\n"
        "No application was deployed, stopped, reloaded or rolled back. "
        "The candidate SHA has not been released by this workflow.\n"
    )


def main() -> int:
    try:
        summary = preflight(os.environ)
        result = 0
    except PreflightError as error:
        summary = f"Production authentication preflight failed: {error}\n\nNo application was deployed.\n"
        result = 1
    except Exception:  # noqa: BLE001 - failures must not print credential-bearing tracebacks
        # No traceback: third-party failures can embed request credentials.
        summary = "Production authentication preflight failed unexpectedly.\n\nNo application was deployed.\n"
        result = 1
    print(summary)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a") as file:
            file.write(summary)
    return result


if __name__ == "__main__":
    sys.exit(main())
