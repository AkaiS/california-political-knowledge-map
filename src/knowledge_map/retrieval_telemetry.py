"""Attach existing retrieval diagnostics to the branch that observed them."""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar

import logfire

from knowledge_map.schemas.retrieval import RetrievalFailureLog

_BRANCH_SPAN: ContextVar[logfire.LogfireSpan | None] = ContextVar(
    "retrieval_branch_span", default=None
)


@contextmanager
def active_branch_span(span: logfire.LogfireSpan | None) -> Iterator[None]:
    token = _BRANCH_SPAN.set(span)
    try:
        yield
    finally:
        _BRANCH_SPAN.reset(token)


def record_branch_failure(diagnostic: RetrievalFailureLog) -> None:
    span = _BRANCH_SPAN.get()
    if span is not None:
        span.set_attributes(
            {
                "failure_stage": diagnostic.stage,
                "failure_kind": diagnostic.failure_kind,
                "diagnostic": diagnostic.safe_diagnostic,
            }
        )


def record_branch_indexes(database: str, indexes: dict[str, str | None]) -> None:
    """Keep the lookup's states; None means a requested index was absent."""
    span = _BRANCH_SPAN.get()
    if span is not None:
        span.set_attributes({"database": database, "indexes": indexes})


@contextmanager
def structural_stage(stage: str) -> Iterator[logfire.LogfireSpan | None]:
    branch = _BRANCH_SPAN.get()
    attributes = branch.attributes if branch is not None else None
    with (
        logfire.span(
            "chat_session.structural_stage",
            chat_session_id=attributes["chat_session_id"],
            audit_schema_version=1,
            stage=stage,
        )
        if attributes is not None
        else nullcontext()
    ) as span:
        yield span
        if span is not None:
            span.set_attribute("status", "succeeded")
