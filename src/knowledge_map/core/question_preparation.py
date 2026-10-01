"""Prepare the Chat Agent's question and obtain approval before retrieval."""

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import nullcontext
from typing import Literal, cast

import httpx
import logfire
from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
)
from pydantic_ai.usage import RunUsage

from knowledge_map.core.exceptions import is_retryable_transport_failure
from knowledge_map.prompts import load_prompt
from knowledge_map.schemas import ModelDeployment
from knowledge_map.schemas.query_preparation import (
    AwaitingQueryApproval,
    DeclinedQuestion,
    QueryApproval,
    QueryRewrite,
    QueryRewriteProposal,
    QuestionAssessment,
    QuestionPreparationResult,
    RewriteRejection,
    RewriteUnavailable,
)
from knowledge_map.utils.agents import create_agent
from knowledge_map.utils.deployments import query_rewriter_deployment_from_environment
from knowledge_map.utils.models import get_chat_model

logger = logging.getLogger(__name__)


def model_failure_kind(error: Exception) -> str:
    if isinstance(error, httpx.TransportError):
        return "transport"
    if isinstance(error, ModelAPIError):
        return "provider"
    if isinstance(error, UnexpectedModelBehavior):
        return "model_output"
    return "unexpected"


QUERY_REWRITER_INSTRUCTIONS = load_prompt("query-rewriter/instructions", version=1)


def get_query_rewriter(
    deployment: ModelDeployment | None = None,
    *,
    cache_model: bool = True,
    capabilities: Sequence[AbstractCapability] = (),
) -> Agent[None, QueryRewriteProposal]:
    """Construct the Query Rewriter through the shared observable factory."""

    return cast(
        Agent[None, QueryRewriteProposal],
        create_agent(
            get_chat_model(
                deployment or query_rewriter_deployment_from_environment(),
                cache=cache_model,
            ),
            name="query_rewriter",
            output_type=QueryRewriteProposal,
            instructions=QUERY_REWRITER_INSTRUCTIONS,
            capabilities=capabilities,
        ),
    )


class QuestionPreparation:
    """Own one question's proposal and approval before handing it to retrieval."""

    def __init__(
        self,
        original_question: str,
        *,
        rewriter: Agent[None, QueryRewriteProposal],
        assess_question_policy_and_coverage: Callable[
            [QueryRewriteProposal], Awaitable[QuestionAssessment]
        ],
        usage: RunUsage | None = None,
        chat_session_id: str | None = None,
    ) -> None:
        self._original_question = original_question
        self._rewriter = rewriter
        self._usage = usage
        self._chat_session_id = chat_session_id
        self._assess_question_policy_and_coverage = assess_question_policy_and_coverage
        self._pending: QueryRewrite | None = None
        self._state: Literal["ready", "preparing", "awaiting_approval", "finished"] = (
            "ready"
        )
        self._rejections: list[RewriteRejection] = []

    @property
    def rejections(self) -> tuple[RewriteRejection, ...]:
        """Retain rejected proposals for feedback and later evaluation."""

        return tuple(self._rejections)

    async def prepare(self) -> QuestionPreparationResult:
        """Rewrite the original request and assess only the resulting question."""

        if self._state != "ready":
            raise ValueError("this question already has a proposal or is finished")
        self._state = "preparing"
        try:
            return await self._prepare()
        finally:
            if self._state == "preparing":
                self._state = "finished"

    async def _prepare(self) -> QuestionPreparationResult:
        with (
            logfire.span(
                "chat_session.query_rewrite",
                chat_session_id=self._chat_session_id,
                audit_schema_version=1,
                proposal_attempt=len(self._rejections) + 1,
            )
            if self._chat_session_id is not None
            else nullcontext()
        ) as proposal_span:
            try:
                rewrite = await self._propose()
            except Exception as error:
                if proposal_span is not None:
                    proposal_span.set_attributes(
                        {
                            "status": "failed",
                            "failure_kind": model_failure_kind(error),
                            "diagnostic": "The Query Rewriter could not prepare a proposal.",
                        }
                    )
                raise
            if isinstance(rewrite, RewriteUnavailable):
                if proposal_span is not None:
                    proposal_span.set_attributes(
                        {
                            "status": "unavailable",
                            "failure_kind": "transport",
                            "diagnostic": rewrite.message,
                        }
                    )
                return rewrite
            if proposal_span is not None:
                proposal_span.set_attributes(
                    {"status": "proposed", **rewrite.model_dump()}
                )
        with (
            logfire.span(
                "chat_session.question_assessment",
                chat_session_id=self._chat_session_id,
                audit_schema_version=1,
                proposal_attempt=len(self._rejections) + 1,
            )
            if self._chat_session_id is not None
            else nullcontext()
        ) as assessment_span:
            try:
                assessment = await self._assess_question_policy_and_coverage(rewrite)
            except Exception as error:
                if assessment_span is not None:
                    assessment_span.set_attributes(
                        {
                            "status": "failed",
                            "failure_kind": model_failure_kind(error),
                            "diagnostic": "The Chat Agent could not assess question policy and coverage.",
                        }
                    )
                raise
            if assessment_span is not None:
                assessment_span.set_attributes(assessment.model_dump(exclude_none=True))
        if assessment.status == "declined":
            self._state = "finished"
            assert assessment.explanation is not None
            return DeclinedQuestion(message=assessment.explanation)
        self._pending = QueryRewrite(
            question=rewrite.question,
            relational=rewrite.relational,
            assessment=assessment,
        )
        self._state = "awaiting_approval"
        return AwaitingQueryApproval(
            approval=QueryApproval(
                question=rewrite.question,
                explanation=assessment.explanation,
                recoverable_portion=assessment.recoverable_portion,
            ),
        )

    async def _propose(self) -> QueryRewriteProposal | RewriteUnavailable:
        try:
            result = await self._rewriter.run(
                json.dumps(
                    {
                        "original_question": self._original_question,
                        "rejections": [
                            rejection.model_dump() for rejection in self._rejections
                        ],
                    }
                ),
                usage=self._usage,
            )
        except (ModelAPIError, httpx.TransportError) as error:
            temporary_request_status = isinstance(
                error, ModelHTTPError
            ) and error.status_code in {408, 429}
            if not temporary_request_status and not is_retryable_transport_failure(
                error
            ):
                raise
            self._state = "finished"
            logger.warning(
                "rewrite_unavailable",
                extra={
                    "event": "rewrite_unavailable",
                    "stage": "query_rewrite",
                    "failure_kind": "transport",
                    "error_type": type(error).__name__,
                },
            )
            return RewriteUnavailable(
                message=(
                    "A temporary network problem prevented rewriting your question. "
                    "The question cannot be answered right now. Please try again later."
                ),
            )
        return result.output

    def approve(self) -> QueryRewrite:
        """Release only the current proposal as the sole retrieval question."""

        if self._pending is None:
            raise ValueError("there is no question awaiting approval")
        approved = self._pending
        self._pending = None
        self._state = "finished"
        return approved

    def reject(self, correction: str | None = None) -> RewriteRejection:
        """Record feedback and require a fresh proposal before approval."""

        if self._pending is None:
            raise ValueError("there is no question awaiting approval")
        rejection = RewriteRejection(
            question=self._pending.question,
            relational=self._pending.relational,
            correction=correction,
        )
        self._rejections.append(rejection)
        self._pending = None
        self._state = "ready"
        logger.info(
            "rewrite_rejected",
            extra={"event": "rewrite_rejected", **rejection.model_dump()},
        )
        return rejection
