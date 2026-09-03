"""`ca-map telemetry` — report the Logfire credential this project runs on.

This is the one command exempt from the token check, because it is what you
run when the check has stopped everything else.  Storing a token is `keyring`'s
job, not this project's:

    uv run keyring set logfire dev-telemetry
"""

from __future__ import annotations

import argparse
from typing import Any

from knowledge_map.utils import telemetry

BOOTSTRAP_ACTION = "telemetry"


def add_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        BOOTSTRAP_ACTION, help="Report the Logfire credential this project runs on"
    )
    actions = parser.add_subparsers(dest="telemetry_action", required=True)
    actions.add_parser("status", help="Say where the token is coming from, if anywhere")


def dispatch(args: argparse.Namespace) -> None:
    del args
    _status()


def _status() -> None:
    credential = telemetry.resolve_credential()
    if credential is None:
        raise SystemExit(telemetry._MISSING_TOKEN_MESSAGE)

    print(f"Logfire token found in {credential.source}.")
    print(
        "Project: "
        + (
            credential.project_url
            or f"unknown to this source (set {telemetry.PROJECT_URL_ENV}); "
            "runs are still traced, but reports cannot link the trace"
        )
    )
