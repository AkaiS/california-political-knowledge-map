import sys
import logging
from typing import Optional, Dict

logger = logging.getLogger("knowledge_map.notifications")

class ConsoleNotifier:
    @staticmethod
    def print_warning_banner(title: str, message: str, details: Optional[Dict[str, str]] = None) -> None:
        """
        Always logs a critical error, and additionally prints a high-visibility 
        warning block to sys.stderr if it is a TTY.
        """
        # 1. ALWAYS Log the critical error so it's never lost
        details_str = ""
        if details:
            details_str = " | Details: " + ", ".join(f"{k}={v}" for k, v in details.items())
        logger.critical(f"[{title.upper()}] {message}{details_str}")

        # 2. ONLY do the visual flair if someone is watching
        if not sys.stderr.isatty():
            return

        border_char = "="
        width = 80
        header = f" {title.upper()} "
        padding = (width - len(header)) // 2
        
        banner_top = border_char * padding + header + border_char * (width - padding - len(header))
        banner_bottom = border_char * width
        
        sys.stderr.write(f"\n{banner_top}\n")
        sys.stderr.write(f"⚠️  CRITICAL: {message}\n")
        
        if details:
            sys.stderr.write("\nDetails:\n")
            for k, v in details.items():
                sys.stderr.write(f"  - {k}: {v}\n")
        sys.stderr.write(f"{banner_bottom}\n\n")
        sys.stderr.flush()

    @classmethod
    def notify_lock_triggered(cls, component: str, lock_file_path: str, error_message: str) -> None:
        """
        Notify when consecutive rate limit failures lock the pipeline.
        """
        details = {
            "Component": component,
            "Lock File Created At": lock_file_path,
            "Last Error Message": error_message,
        }
        cls.print_warning_banner(
            title="Pipeline Lock Triggered",
            message="Rate limit threshold exceeded. Ingestion pipeline is now LOCKED.",
            details=details
        )

    @classmethod
    def notify_lock_detected(cls, component: str, lock_file_path: str, timestamp: str, error_message: str) -> None:
        """
        Notify when a lock file is detected at startup.
        """
        details = {
            "Component Locked": component,
            "Lock File Location": lock_file_path,
            "Locked Since": timestamp,
            "Original Error": error_message,
        }
        cls.print_warning_banner(
            title="Pipeline Locked (Startup Aborted)",
            message="An active pipeline lock was detected. To release it, run the 'janitor' command.",
            details=details
        )

    @classmethod
    def notify_critical_failure(cls, error_title: str, message: str, details: Optional[Dict[str, str]] = None) -> None:
        """
        Notify when an unrecoverable failure (such as database connectivity) occurs.
        """
        cls.print_warning_banner(
            title=error_title,
            message=message,
            details=details
        )

    @classmethod
    def notify_discovery_drift(cls, publication_id: str, url: str) -> None:
        """
        Notify when a discovery run returns 0 candidates from a successful response.
        """
        details = {
            "Publication ID": publication_id,
            "Listing URL": url,
        }
        cls.print_warning_banner(
            title="Discovery Drift Warning",
            message="Discovery run returned 0 candidate URLs from a successful (200 OK) response. Possible layout drift or over-restrictive filters.",
            details=details
        )

    @classmethod
    def notify_circuit_breaker_tripped(cls, publication_id: str, tripping_url: str, failure_points: int) -> None:
        """
        Notify when validation circuit breaker trips for a publication.
        """
        details = {
            "Publication ID": publication_id,
            "Tripping URL": tripping_url,
            "Failure Points": str(failure_points),
        }
        cls.print_warning_banner(
            title="Circuit Breaker Tripped",
            message=f"Validation circuit breaker tripped for '{publication_id}'. Validation pipeline is now PAUSED.",
            details=details
        )

