"""Configure Logfire, or refuse to run.

A run nobody can inspect afterwards teaches nothing, so a missing Logfire
token is a startup failure rather than a warning.  The token itself lives in
the OS keychain; see `docs/agents/secrets.md`.
"""

import json
import logging
import os
import re
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import logfire
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_CONFIGURATION_LOCK = threading.Lock()
_configured = False

# The credential this process configured Logfire with.  Held because a report
# is written long after the run began, and the sources are mutable: re-reading
# them then can name a project this process never reported to.
_credential: "LogfireCredential | None" = None

LOGFIRE_TOKEN_ENV = "LOGFIRE_TOKEN"
PROJECT_URL_ENV = "LOGFIRE_PROJECT_URL"

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


_AUDIT_SESSION_FIELDS = {
    ("attributes", "original_question"),
    ("attributes", "question"),
    ("attributes", "approved_question"),
    ("attributes", "correction"),
    ("attributes", "explanation"),
    ("attributes", "recoverable_portion"),
    ("attributes", "model_deployments"),
    ("attributes", "coverage"),
    ("attributes", "accepted_pieces"),
    ("attributes", "wiring"),
    ("attributes", "bindings"),
    ("attributes", "validated_query"),
    ("attributes", "bound_values"),
    ("attributes", "eligible_branches"),
    ("attributes", "fused_chunk_ids"),
    ("attributes", "selected_chunk_ids"),
    ("attributes", "omitted_chunks"),
    ("attributes", "rendered_text"),
    ("attributes", "selected_sources"),
}
_SESSION_CREDENTIAL = re.compile(
    r"\bsession(?:[._-]*id|[._ -]*(?:token|key|cookie|secret|credential|auth))\b",
    re.IGNORECASE,
)


def _contains_secret_match(value: object, pattern: re.Pattern[str]) -> bool:
    if isinstance(value, str):
        return bool(_SESSION_CREDENTIAL.search(value)) or any(
            found.group(0).casefold() != "session" for found in pattern.finditer(value)
        )
    if isinstance(value, Mapping):
        return any(
            _contains_secret_match(key, pattern)
            or _contains_secret_match(item, pattern)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return any(_contains_secret_match(item, pattern) for item in value)
    return False


def scrub_chat_audit_attribute(match: logfire.ScrubMatch) -> object:
    """Keep political uses of "session" without bypassing secret matches."""
    if match.path == ("attributes", "chat_session_id"):
        return match.value
    if (
        match.path[:2] in _AUDIT_SESSION_FIELDS
        and match.pattern_match.group(0).casefold() == "session"
        and not _contains_secret_match(match.path[2:], match.pattern_match.re)
        and not _contains_secret_match(match.value, match.pattern_match.re)
    ):
        return match.value
    return None


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


@dataclass(frozen=True)
class LogfireCredential:
    """A write token together with the project it reports to.

    The two travel as one value because resolving them separately lets a token
    from one source pair with a project named by another: a trace recorded
    under the keychain's project would then be advertised under whichever
    project a stale credentials file happened to name, and the link would go
    somewhere the run never reported to.  ``project_url`` is None when no
    source can vouch for the pairing.
    """

    token: str
    project_url: str | None
    source: str


def resolve_credential() -> LogfireCredential | None:
    """Find the token and its project from one source: env, keychain, file."""

    # A token supplied out of band carries no project of its own.  The
    # operator may declare the companion, which is asserted rather than
    # checked and so is only ever a fallback for what Logfire resolves from
    # the token; nothing else may stand in for it.
    declared_project = os.environ.get(PROJECT_URL_ENV)

    environment_token = os.environ.get(LOGFIRE_TOKEN_ENV)
    if environment_token:
        return LogfireCredential(
            environment_token,
            declared_project,
            f"the {LOGFIRE_TOKEN_ENV} environment variable",
        )

    keychain_token = _keychain_token()
    if keychain_token:
        return LogfireCredential(
            keychain_token,
            declared_project,
            f"the keychain ({KEYRING_SERVICE}/{KEYRING_USERNAME})",
        )

    credentials = _credentials()
    file_token = credentials.get("token")
    if file_token:
        # This file names the project its own token belongs to, which is the
        # one pairing this process can verify rather than assume.
        return LogfireCredential(
            file_token,
            credentials.get("project_url"),
            ".logfire/logfire_credentials.json in this directory",
        )

    return None


def resolve_token() -> str | None:
    """The Logfire write token this run will report with, if there is one."""

    credential = resolve_credential()
    return credential.token if credential else None


def _verified_project_url() -> str | None:
    """The project Logfire itself resolved from the token it was given.

    Logfire validates a write token against the API and learns which project
    it belongs to.  That answer comes from the token, so it is the only one
    that cannot name a project the run did not report to.

    Read defensively: it is Logfire's own internal state, and a version that
    stops exposing it must leave this degrading to the declared project rather
    than raising in the middle of writing a report.
    """

    try:
        url = getattr(logfire.DEFAULT_LOGFIRE_INSTANCE.config, "_project_url", None)
    except AttributeError:
        return None
    return url if isinstance(url, str) and url else None


def project_url() -> str | None:
    """The project this process reported to, when it is known.

    Prefers what Logfire established from the token itself, which settles a
    declared LOGFIRE_PROJECT_URL that names somewhere else.  Otherwise answers
    from the credential configure() was given, so that rotating a token or
    writing a credentials file mid-run cannot redirect a finished run's link;
    a fresh resolution is the last resort, for a process that configured
    nothing and therefore recorded no trace for a link to mislead about.
    """

    verified = _verified_project_url()
    if verified:
        return verified

    credential = _credential or resolve_credential()
    return credential.project_url if credential else None


def setup_telemetry() -> None:
    """Configure Logfire before any model client or Pydantic AI agent runs.

    Raises `TelemetryNotConfiguredError` when no token can be found, so that a
    run which would vanish unrecorded fails at its start instead of at its end.
    """

    global _configured, _credential
    if _configured:
        return

    with _CONFIGURATION_LOCK:
        if _configured:
            return

        # Read .env here rather than at each entry point: a token supplied that
        # way must be visible before configure(), whichever caller arrives first.
        load_dotenv()

        is_testing = _is_testing()
        # Resolved once and kept: every later reader must answer about the run
        # that happened, not about the credential sources as they stand then.
        credential = None if is_testing else resolve_credential()
        token = credential.token if credential else None
        if not is_testing and credential is None:
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
            scrubbing=logfire.ScrubbingOptions(callback=scrub_chat_audit_attribute),
        )

        # This must follow configure() and precede Agent construction.
        logfire.instrument_pydantic_ai()

        # Model clients use HTTPX. Keep transport timing, status, and errors without
        # copying every request and response payload into low-level telemetry.
        logfire.instrument_httpx(capture_all=False)
        logfire.instrument_system_metrics()

        _credential = credential
        _configured = True
        logger.debug("Logfire telemetry initialized successfully")
