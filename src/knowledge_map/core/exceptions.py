from contextlib import contextmanager

import httpx
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError

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

@contextmanager
def transport_failures_as_pipeline_errors(component: str):
    """Translate an exhausted transport retry into a pipeline error category.

    The HTTP client behind every LLM model retries a rate limit or a dropped
    connection at the request that hit it.  What reaches this seam has already
    outlived that budget, so it is mapped by the status the final response
    carried -- 429 to the rate limit error, anything else to the connectivity
    error -- rather than by reading the exception's text.  Batch ingestion's
    consecutive-failure lock branches on those two types.
    """

    try:
        yield
    except (ModelAPIError, httpx.HTTPError) as error:
        status_code = _final_status_code(error)
        pipeline_error = (
            PipelineRateLimitError if status_code == 429 else PipelineConnectivityError
        )
        raise pipeline_error(
            message=str(error),
            component=component,
            original_exception=error,
        ) from error


def _final_status_code(error: Exception) -> int | None:
    """The status the final response carried, when there was one."""

    if isinstance(error, ModelHTTPError):
        return error.status_code
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code
    return None
