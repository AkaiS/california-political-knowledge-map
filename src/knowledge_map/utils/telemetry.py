"""Configure Logfire, or refuse to run.

A run nobody can inspect afterwards teaches nothing, so a missing Logfire
token is a startup failure rather than a warning.  The token itself lives in
the OS keychain; see `docs/agents/secrets.md`.
"""

import json
import logging
import os
import sys
import threading
from pathlib import Path

import logfire
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_CONFIGURATION_LOCK = threading.Lock()
_configured = False

LOGFIRE_TOKEN_ENV = "LOGFIRE_TOKEN"

# Where `keyring set logfire dev-telemetry` puts the write token.
KEYRING_SERVICE = "logfire"
KEYRING_USERNAME = "dev-telemetry"

# Set this when a run genuinely cannot reach Logfire — an offline machine, a
# first checkout before the keychain entry exists.  Nothing else may skip the
# check; the point is that an unobservable run is a decision, not an accident.
ALLOW_UNTRACED = "KNOWLEDGE_MAP_ALLOW_UNTRACED"

_MISSING_TOKEN_MESSAGE = f"""\
Logfire has no token, so this run would produce no traces to inspect.

Store one in the keychain (it is read from there on every later run):

  uv run keyring set {KEYRING_SERVICE} {KEYRING_USERNAME}

or export {LOGFIRE_TOKEN_ENV} for this shell.  `ca-map telemetry status` says
which of those a run is using.  To run without observability anyway, set
{ALLOW_UNTRACED}=1."""


class TelemetryNotConfiguredError(RuntimeError):
    """Raised when a run would be unobservable."""


def _is_testing() -> bool:
    return (
        "pytest" in sys.modules
        or os.environ.get("PYTEST_CURRENT_TEST") is not None
        or (
            "unittest" in sys.modules
            and any("unittest" in arg or "pytest" in arg for arg in sys.argv)
        )
    )


def _keychain_token() -> str | None:
    """Read the write token from the OS keychain.

    Imported lazily: a machine with no keychain backend must still be able to
    run on an exported LOGFIRE_TOKEN.
    """

    try:
        import keyring
        import keyring.errors
    except ImportError:
        return None

    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except keyring.errors.KeyringError:
        logger.debug("keychain unavailable while resolving the Logfire token")
        return None


def _credentials(directory: Path | None = None) -> dict[str, str]:
    """Read a `logfire projects use` credentials file, if one is here.

    Logfire looks for this itself, but only under the process's working
    directory.  Reading it explicitly lets a token found this way be passed to
    `configure()`, and surfaces the project URL that turns a trace id into a link.
    """

    path = (directory or Path(".logfire")) / "logfire_credentials.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def resolve_token() -> str | None:
    """Find the Logfire write token: environment, then keychain, then file."""

    return (
        os.environ.get(LOGFIRE_TOKEN_ENV)
        or _keychain_token()
        or _credentials().get("token")
    )


def project_url() -> str | None:
    """The Logfire project a trace id can be linked into, when it is known."""

    return os.environ.get("LOGFIRE_PROJECT_URL") or _credentials().get("project_url")


def setup_telemetry() -> None:
    """Configure Logfire before any model client or Pydantic AI agent runs.

    Raises `TelemetryNotConfiguredError` when no token can be found, so that a
    run which would vanish unrecorded fails at its start instead of at its end.
    """

    global _configured
    if _configured:
        return

    with _CONFIGURATION_LOCK:
        if _configured:
            return

        # Read .env here rather than at each entry point: a token supplied that
        # way must be visible before configure(), whichever caller arrives first.
        load_dotenv()

        is_testing = _is_testing()
        token = None if is_testing else resolve_token()
        if not is_testing and token is None:
            if os.environ.get(ALLOW_UNTRACED, "").lower() not in ("1", "true", "yes"):
                raise TelemetryNotConfiguredError(_MISSING_TOKEN_MESSAGE)
            logger.warning("%s is set; this run will not be observable", ALLOW_UNTRACED)

        logfire.configure(
            token=token,
            advanced=logfire.AdvancedOptions(
                base_url="https://logfire-us.pydantic.dev"
            ),
            service_name="california-political-knowledge-map",
            service_version="0.1.0",
            environment=(
                "test"
                if is_testing
                else os.environ.get("DEPLOYMENT_ENVIRONMENT", "development")
            ),
            send_to_logfire=False if is_testing else "if-token-present",
        )

        # This must follow configure() and precede Agent construction.
        logfire.instrument_pydantic_ai()

        # Model clients use HTTPX. Full capture exposes the OpenRouter request and
        # response beneath the parent Pydantic AI run span; Logfire scrubs common
        # credential fields before export.
        logfire.instrument_httpx(capture_all=True)
        logfire.instrument_system_metrics()

        _configured = True
        logger.debug("Logfire telemetry initialized successfully")
