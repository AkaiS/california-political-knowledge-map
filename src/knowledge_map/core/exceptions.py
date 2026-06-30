import socket
import httpx
from typing import Optional
from knowledge_map.adapters.coreference import CoreferenceResolutionError
from knowledge_map.adapters.extraction import ExtractionError

class PipelineException(Exception):
    """Base exception for pipeline execution issues."""
    def __init__(self, message: str, component: str, original_exception: Exception) -> None:
        self.component = component
        self.original_exception = original_exception
        super().__init__(message)

class PipelineRateLimitError(PipelineException):
    """Raised when a rate limit is hit and cannot be retried or exceeds cap."""
    pass

class PipelineConnectivityError(PipelineException):
    """Raised when connectivity errors are exhausted."""
    pass

class PipelineLockError(Exception):
    """Raised when a pipeline lock file exists or is written."""
    pass

def classify_exception(e: Exception) -> bool:
    """
    Identifies non-breaking errors that can be routed to the Dead Letter Queue
    rather than aborting the batch process.
    """
    return isinstance(e, (CoreferenceResolutionError, ExtractionError))

def classify_api_error(e: Exception) -> Optional[str]:
    """
    Identifies RATE_LIMIT and CONNECTIVITY error types from exceptions.
    """
    curr = e
    while curr is not None:
        # Check HTTP status code
        if hasattr(curr, "response") and getattr(curr.response, "status_code", None) == 429:
            return "RATE_LIMIT"
        if hasattr(curr, "status_code") and getattr(curr, "status_code") == 429:
            return "RATE_LIMIT"
        
        # Check specific types
        if isinstance(curr, (httpx.RequestError, socket.timeout, TimeoutError, ConnectionError)):
            return "CONNECTIVITY"
            
        err_str = str(curr).lower()
        if "429" in err_str or "rate limit" in err_str or "rate_limit" in err_str or "too many requests" in err_str:
            return "RATE_LIMIT"
            
        # Move to context or cause
        next_err = getattr(curr, "__context__", None) or getattr(curr, "__cause__", None)
        if next_err == curr:
            break
        curr = next_err
        
    # Final keyword check on the original exception's message
    err_str = str(e).lower()
    connectivity_keywords = [
        "timeout", "timed out", "connection error", "connectivity", 
        "dns", "socket", "connection refused", "connection reset"
    ]
    if any(keyword in err_str for keyword in connectivity_keywords):
        return "CONNECTIVITY"
        
    return None

def get_retry_after(e: Exception) -> Optional[int]:
    """
    Recursively checks for the Retry-After header in the exception context.
    """
    curr = e
    while curr is not None:
        if hasattr(curr, "response") and hasattr(curr.response, "headers"):
            headers = curr.response.headers
            val = headers.get("retry-after") or headers.get("Retry-After")
            if val:
                try:
                    return int(val)
                except ValueError:
                    pass
        next_err = getattr(curr, "__context__", None) or getattr(curr, "__cause__", None)
        if next_err == curr:
            break
        curr = next_err
    return None

