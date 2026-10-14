"""Release the exact reviewed main commit to the production Bottle app."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from production_preflight import (
    PreflightError,
    ProductionAccess,
    observed_revision,
    production_access,
    run_quiet,
    subprocess_environment,
    trusted_revision,
)

REPOSITORY_URL = "https://github.com/AkaiS/california-political-knowledge-map"
PODMAN = "cd ~/openhost && /home/host/.pixi/bin/pixi run -e dev podman"
MAX_DISK_USED_PERCENT = 80
SHUTDOWN_SECONDS = 180
RELOAD_SECONDS = 75 * 60
READY_SECONDS = 15 * 60


@dataclass
class Progress:
    candidate: str = "unavailable"
    previous: str = "unavailable"
    stage: str = "starting"
    stopped: bool = False

    def enter(self, stage: str) -> None:
        self.stage = stage
        print(f"Release stage: {stage}.", flush=True)


def main_tip(environment: Mapping[str, str]) -> str:
    output = run_quiet(
        ["git", "ls-remote", REPOSITORY_URL, "refs/heads/main"],
        subprocess_environment(environment),
        "Reading the main branch tip",
    )
    tip = output.split("\t", 1)[0].strip()
    if not re.fullmatch(r"[0-9a-f]{40}", tip):
        raise PreflightError("The main branch tip is unavailable.")
    return tip


def remote(access: ProductionAccess, command: str, label: str, timeout=60) -> str:
    return run_quiet(access.ssh(command), access.environment, label, timeout).strip()


def container_running(access: ProductionAccess, container: str) -> bool:
    state = remote(
        access,
        f"{PODMAN} inspect --format '{{{{.State.Running}}}}' {container}",
        "Reading the container state",
    )
    if state not in {"true", "false"}:
        raise PreflightError("The container state is unavailable.")
    return state == "true"


def app_id(access: ProductionAccess) -> str:
    output = run_quiet(
        access.curl("-fsS", f"https://{access.hostname}/api/apps"),
        access.environment,
        "Listing Bottle applications",
    )
    try:
        matches = [
            app.get("app_id")
            for app in json.loads(output)
            if app.get("name") == access.app_name
        ]
    except (ValueError, AttributeError, TypeError):
        raise PreflightError("The Bottle application list is malformed.") from None
    if len(matches) != 1 or not re.fullmatch(r"[A-Za-z0-9]+", str(matches[0])):
        raise PreflightError("The Bottle application ID is not unique.")
    return matches[0]


def http_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def release(
    environment: Mapping[str, str],
    progress: Progress,
    *,
    ready: Callable[[str], bool] = http_ready,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    revision = trusted_revision(environment)
    progress.candidate = revision
    # An approval can arrive after a newer merge; releasing it would roll back.
    progress.enter("checking the main branch tip")
    if main_tip(environment) != revision:
        raise PreflightError(
            "A newer main commit exists; approve the release for that commit."
        )
    with production_access(environment) as access:
        progress.enter("reading the current release")
        status = run_quiet(
            access.bottle("app", "status", access.app_name),
            access.environment,
            "Bottle application status",
        )
        progress.previous = observed_revision(status)
        if progress.previous == revision:
            return (
                f"Production already runs `{revision}`.\n\n"
                "No application was stopped or reloaded.\n"
            )

        progress.enter("checking free disk space")
        used = remote(access, "df -P / | awk 'NR==2 {print $5}'", "Reading disk use")
        if not re.fullmatch(r"[0-9]{1,3}%", used):
            raise PreflightError("Disk use is unavailable.")
        if int(used[:-1]) > MAX_DISK_USED_PERCENT:
            raise PreflightError(f"Disk use {used} leaves less than 20% free.")
        identifier = app_id(access)

        # Bottle's ordinary stop allows ten seconds; Neo4j needs longer to stop
        # cleanly, so supervisor shuts services down before the rebuild.
        container = f"openhost-{access.app_name}"
        progress.enter("shutting down services")
        if container_running(access, container):
            progress.stopped = True
            remote(
                access,
                # The exec can lose its connection as the container exits, so
                # the state poll below decides whether shutdown finished.
                f"{PODMAN} update --restart=no {container} && {{ {PODMAN} exec "
                f"{container} /app/.venv/bin/supervisorctl "
                "-c /app/deployment/supervisord.conf shutdown || true; }",
                "Shutting down services",
                timeout=SHUTDOWN_SECONDS,
            )
            deadline = clock() + SHUTDOWN_SECONDS
            while container_running(access, container):
                if clock() > deadline:
                    raise PreflightError("The container did not stop in time.")
                sleep(5)
        progress.stopped = True

        progress.enter("pinning the candidate revision")
        run_quiet(
            access.curl(
                "-fsS",
                "-X",
                "POST",
                f"https://{access.hostname}/set_app_remote/{identifier}",
                "-H",
                "Content-Type: application/json",
                "--data",
                json.dumps({"repo_url": f"{REPOSITORY_URL}@{revision}"}),
            ),
            access.environment,
            "Pinning the candidate revision",
        )

        progress.enter("rebuilding and restarting")
        run_quiet(
            access.bottle("app", "reload", access.app_name, "--update", "--wait"),
            access.environment,
            "Rebuilding and restarting",
            timeout=RELOAD_SECONDS,
        )

        progress.enter("verifying the release")
        status = run_quiet(
            access.bottle("app", "status", access.app_name),
            access.environment,
            "Bottle application status",
        )
        if observed_revision(status) != revision:
            raise PreflightError("Bottle does not report the candidate revision.")
        url = f"https://{access.app_name}.{access.hostname}/health/ready"
        deadline = clock() + READY_SECONDS
        while not ready(url):
            if clock() > deadline:
                raise PreflightError("The application did not become ready in time.")
            sleep(10)
    return (
        f"Released `{revision}` to production.\n\n"
        f"Previous revision: `{progress.previous}`.\n\n"
        "Bottle reports the candidate revision and readiness passed.\n"
    )


def failure_summary(reason: str, progress: Progress) -> str:
    summary = (
        f"Production release failed while {progress.stage}: {reason}\n\n"
        f"Candidate revision: `{progress.candidate}`.\n\n"
        f"Previous revision: `{progress.previous}`.\n\n"
    )
    if progress.stopped:
        return summary + (
            "The application was stopped and may be unavailable. Inspect "
            "`bottle app status`, then reload a known-good revision using "
            "docs/cloud-deployment.md.\n"
        )
    return summary + "The running application was not changed.\n"


def main() -> int:
    progress = Progress()
    try:
        summary = release(os.environ, progress)
        result = 0
    except PreflightError as error:
        summary = failure_summary(str(error), progress)
        result = 1
    except Exception:  # noqa: BLE001 - failures must not print credential-bearing tracebacks
        summary = failure_summary("unexpected failure.", progress)
        result = 1
    print(summary)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a") as file:
            file.write(summary)
    return result


if __name__ == "__main__":
    sys.exit(main())
