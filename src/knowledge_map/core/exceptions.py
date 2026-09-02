from contextlib import contextmanager

import httpx
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError

from knowledge_map.adapters.coreference import CoreferenceResolutionError
from knowledge_map.adapters.extraction import ExtractionError
from knowledge_map.adapters.policy_areas import PolicyAreaClassificationError


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

    @property
    def retryable(self) -> bool:
        """Whether the original provider failure can succeed on a later run."""

        return _is_retryable_transport_failure(self.original_exception)


class PipelineLockError(Exception):
    """Raised when a pipeline lock file exists or is written."""
    pass


def classify_exception(e: Exception) -> bool:
    """
    Identifies non-breaking errors that can be routed to the Dead Letter Queue
    rather than aborting the batch process.
    """
    return isinstance(
        e,
        (CoreferenceResolutionError, ExtractionError, PolicyAreaClassificationError),
    )


@contextmanager
def transport_failures_as_pipeline_errors(component: str):
    """Translate an exhausted transport retry into a pipeline error category.

    Wrap a stage that calls a model.  Failures arrive here having already
    outlived the client's own retry budget, and are mapped by final status:
    429 to the rate limit error, anything else to connectivity.  Batch
    ingestion's consecutive-failure lock branches on those two types.
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


_RETRYABLE_SERVER_STATUS_CODES = frozenset({
    500,
    502,
    503,
    504,
    524,
    529,
})


def _is_retryable_transport_failure(error: Exception) -> bool:
    """Classify typed failures that may succeed when the Story is retried."""

    if isinstance(error, httpx.TransportError):
        return True
    if isinstance(error, ModelAPIError) and not isinstance(error, ModelHTTPError):
        return True
    return _final_status_code(error) in _RETRYABLE_SERVER_STATUS_CODES
