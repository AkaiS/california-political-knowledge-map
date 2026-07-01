import os
import sys
import logging

logger = logging.getLogger(__name__)

def setup_telemetry() -> None:
    """Configure Pydantic Logfire telemetry."""
    if getattr(setup_telemetry, "_configured", False):
        return

    try:
        import logfire
        
        # Check if running in a testing environment (pytest/unittest)
        is_testing = (
            "pytest" in sys.modules
            or os.environ.get("PYTEST_CURRENT_TEST") is not None
            or (
                "unittest" in sys.modules
                and any("unittest" in arg or "pytest" in arg for arg in sys.argv)
            )
        )
        
        # Disable remote exporting in test suite runs by default
        send_to_logfire = 'if-token-present' if not is_testing else False
        
        logfire.configure(
            advanced=logfire.AdvancedOptions(
                base_url="https://logfire-us.pydantic.dev"
            ),
            send_to_logfire=send_to_logfire
        )
        
        # Instrument Pydantic AI
        logfire.instrument_pydantic_ai()
        
        # Instrument HTTPX calls (capturing LLM request payloads)
        logfire.instrument_httpx(capture_all=True)
        
        # Instrument host/system metrics (installed with [system-metrics])
        logfire.instrument_system_metrics()
        
        setup_telemetry._configured = True
        logger.debug("Logfire telemetry initialized successfully.")
    except ImportError:
        logger.warning("Logfire package not found. Telemetry is disabled.")
    except Exception as e:
        logger.warning(f"Failed to initialize Logfire telemetry: {e}")
