import logging
import os
import sys
import threading

import logfire

logger = logging.getLogger(__name__)

_CONFIGURATION_LOCK = threading.Lock()
_configured = False


def _is_testing() -> bool:
    return (
        "pytest" in sys.modules
        or os.environ.get("PYTEST_CURRENT_TEST") is not None
        or (
            "unittest" in sys.modules
            and any("unittest" in arg or "pytest" in arg for arg in sys.argv)
        )
    )


def setup_telemetry() -> None:
    """Configure Logfire before any model client or Pydantic AI agent runs."""

    global _configured
    if _configured:
        return

    with _CONFIGURATION_LOCK:
        if _configured:
            return

        is_testing = _is_testing()
        logfire.configure(
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
