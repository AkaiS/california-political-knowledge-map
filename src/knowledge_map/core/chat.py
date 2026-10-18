"""Assess a question and prepare source guidance with the existing Chat Agent."""

import json
import logging
import re
from calendar import monthrange
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime
from graphlib import TopologicalSorter
from time import strptime
from typing import Literal, cast
from uuid import uuid4

import logfire
from pydantic import ValidationError
from pydantic_ai import Agent, NativeOutput, capture_run_messages
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
)
from pydantic_ai.usage import RunUsage

from knowledge_map.chat_telemetry import ChatSessionSettings
from knowledge_map.core.evidence import render_evidence_context
from knowledge_map.core.question_preparation import (
    QuestionPreparation,
    model_failure_kind,
)
from knowledge_map.core.retrieval import RetrievalCoordinator
from knowledge_map.prompts import load_prompt
from knowledge_map.schemas import DeploymentKind, ModelDeployment
from knowledge_map.schemas.query_preparation import (
    QueryRewrite,
    QueryRewriteProposal,
    QuestionAssessment,
    QuestionPreparationResult,
    RewriteRejection,
)
from knowledge_map.schemas.retrieval import (
    ArticleGroup,
    ArticleGroupMember,
    CoverageDescription,
    EvidenceAssemblyFailure,
    EvidencePackage,
    MonthlyCoverage,
    NonemptyText,
    RetrievalAnswer,
    RetrievalValue,
    SourceDisagreement,
    SourceRelevanceNote,
    UnmatchedRequest,
)
from knowledge_map.utils.agents import create_agent
from knowledge_map.utils.models import DEFAULT_LOCAL_CHAT_MODEL, get_chat_model

logger = logging.getLogger(__name__)

CHAT_INSTRUCTIONS = load_prompt("chat/instructions", version=16)

QUESTION_POLICY = load_prompt("chat/question-policy", version=2)


def _resolve_as_of(as_of: datetime | None) -> datetime:
    resolved = as_of if as_of is not None else datetime.now(UTC)
    if resolved.utcoffset() is None:
        raise ValueError("Chat Session as_of must include a timezone")
    return resolved.astimezone(UTC)


def _date_context(as_of: datetime) -> dict[str, str]:
    return {"as_of": as_of.isoformat(), "current_date": as_of.date().isoformat()}


def _guidance_failure_kind(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return "validation"
    return model_failure_kind(error)


def _rejected_output_attributes(
    error: BaseException, messages: Sequence[ModelMessage]
) -> dict[str, object]:
    """Show the model output the Chat Agent rejected and why.

    Pydantic AI content capture is off, so without this a guidance failure only
    says the output was unusable, not what the model actually sent.
    """
    attributes: dict[str, object] = {}
    responses = [message for message in messages if isinstance(message, ModelResponse)]
    if responses:
        attributes["model_response"] = ModelMessagesTypeAdapter.dump_python(
            [responses[-1]], mode="json"
        )[0]
    if error.__cause__ is not None:
        attributes["output_error"] = str(error.__cause__)
    return attributes


class RetrievalGuidance(RetrievalValue):
    """The Chat Agent's guidance about the already verified source selection."""

    introduction: NonemptyText | None = None
    source_notes: tuple[SourceRelevanceNote, ...] = ()
    disagreements: tuple[SourceDisagreement, ...] = ()
    groups: tuple[ArticleGroup, ...] = ()
    unmatched_requests: tuple[UnmatchedRequest, ...] = ()


def _publication_bounded_guidance(
    guidance: RetrievalGuidance, package: EvidencePackage
) -> RetrievalGuidance:
    assessment = package.execution.request.rewrite.assessment
    first = assessment.publication_date_from
    last = assessment.publication_date_through
    if first is None and last is None:
        return guidance
    excluded = set()
    for source in package.sources:
        published = source.citation.published_date
        try:
            # Use the publication's stated day, without converting its timezone
            # or inventing a day for missing or incomplete citation metadata.
            day = datetime.fromisoformat(published).date() if published else None
        except ValueError:
            day = None
        if day is None or (first and day < first) or (last and day > last):
            excluded.add(source.citation.source_article_id)
    return guidance.model_copy(
        update={
            "source_notes": tuple(
                note
                for note in guidance.source_notes
                if note.source_article_id not in excluded
            )
        }
    )


def _event_date_bounds(value: str) -> tuple[date, date] | None:
    for date_format in ("%Y", "%Y-%m", "%Y-%m-%d", "%B %Y", "%B %d, %Y"):
        try:
            earliest = date(*strptime(value, date_format)[:3])
        except ValueError:
            continue
        latest = earliest
        if date_format == "%Y":
            latest = earliest.replace(month=12, day=31)
        elif date_format in {"%Y-%m", "%B %Y"}:
            latest = earliest.replace(day=monthrange(earliest.year, earliest.month)[1])
        return earliest, latest
    return None


def _order_event_members(
    members: list[ArticleGroupMember], *, newest_first: bool
) -> list[ArticleGroupMember]:
    bounds = []
    for member in members:
        assert member.reported_event_date is not None
        period = _event_date_bounds(member.reported_event_date)
        assert period is not None
        bounds.append(period)
    # Overlapping periods cannot establish event order. Honor every comparable
    # pair, using model order to choose between the remaining available members.
    predecessors = {
        index: [
            other_index
            for other_index, other in enumerate(bounds)
            if (period[1] < other[0] if newest_first else other[1] < period[0])
        ]
        for index, period in enumerate(bounds)
    }
    timeline = TopologicalSorter(predecessors)
    timeline.prepare()
    ready: set[int] = set()
    ordered = []
    while timeline.is_active():
        ready.update(timeline.get_ready())
        index = min(ready)
        ready.remove(index)
        ordered.append(members[index])
        timeline.done(index)
    return ordered


def _included_groups(
    guidance: RetrievalGuidance, package: EvidencePackage
) -> tuple[ArticleGroup, ...]:
    included = {note.source_article_id for note in guidance.source_notes}
    passages = {
        source.citation.source_article_id: tuple(
            passage.text for passage in source.passages
        )
        for source in package.sources
    }
    groups = []
    for group in guidance.groups:
        members = []
        for member in group.members:
            if member.source_article_id not in included:
                continue
            event_date = member.reported_event_date
            if event_date and not (
                group.kind == "timeline"
                and group.order in {"event_asc", "event_desc"}
                and re.fullmatch(
                    r"(?:\d{4}(?:-\d{2}(?:-\d{2})?)?|"
                    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                    r"(?: \d{1,2},)? \d{4})",
                    event_date,
                )
                and _event_date_bounds(event_date) is not None
                and any(
                    event_date in text
                    for text in passages.get(member.source_article_id, ())
                )
            ):
                event_date = None
            validated = member.model_copy(update={"reported_event_date": event_date})
            if validated not in members:
                members.append(validated)
        if not members:
            continue
        order = group.order
        if order in {"event_asc", "event_desc"}:
            dated = [member for member in members if member.reported_event_date]
            undated = [member for member in members if not member.reported_event_date]
            requested = package.execution.request.rewrite.assessment.reading_order
            if requested in {"event_asc", "event_desc"}:
                order = requested
            members = (
                _order_event_members(dated, newest_first=order == "event_desc")
                + undated
            )
        groups.append(
            group.model_copy(update={"members": tuple(members), "order": order})
        )
    return tuple(groups)


async def generate_retrieval_answer(
    agent: Agent[None, QuestionAssessment],
    package: EvidencePackage,
    *,
    original_question: str,
    chat_session_id: str,
    usage: RunUsage,
    as_of: datetime | None = None,
) -> RetrievalAnswer:
    """Generate and validate guidance against the exact assembled evidence."""
    resolved_as_of = _resolve_as_of(as_of)
    rewrite = package.execution.request.rewrite
    with logfire.span(
        "chat_session.guidance",
        chat_session_id=chat_session_id,
        audit_schema_version=1,
    ) as span:
        try:
            with capture_run_messages() as messages:
                result = await agent.run(
                    render_evidence_context(package),
                    message_history=[
                        ModelRequest(
                            parts=[
                                UserPromptPart(
                                    json.dumps(_date_context(resolved_as_of))
                                )
                            ]
                        ),
                        ModelRequest(parts=[UserPromptPart(original_question)]),
                    ],
                    output_type=RetrievalGuidance,
                    usage=usage,
                )
            guidance = _publication_bounded_guidance(result.output, package)
            disclosures = list(package.failure_disclosures)
            structural_empty = package.execution.structural_empty_disclosure
            if structural_empty:
                disclosures.append(structural_empty)
            if rewrite.assessment.status == "deferred":
                assert rewrite.assessment.explanation is not None
                disclosures.append(rewrite.assessment.explanation)
            if result.output.introduction:
                disclosures.append(result.output.introduction)
            answer = RetrievalAnswer(
                guidance_contract=4,
                evidence=package,
                introduction="\n\n".join(disclosures) or None,
                source_notes=guidance.source_notes,
                disagreements=result.output.disagreements,
                groups=_included_groups(guidance, package),
                unmatched_requests=result.output.unmatched_requests,
            )
        except Exception as error:
            failure_kind = _guidance_failure_kind(error)
            span.set_attributes(
                {
                    "status": "failed",
                    "failure_kind": failure_kind,
                    "diagnostic": "The Chat Agent could not prepare retrieval guidance.",
                }
            )
            if failure_kind == "model_output":
                span.set_attributes(_rejected_output_attributes(error, messages))
            raise
        span.set_attribute("status", "succeeded")
        return answer


def get_chat_agent(
    deployment: ModelDeployment | None = None,
    *,
    cache_model: bool = True,
    capabilities: Sequence[AbstractCapability] = (),
) -> Agent[None, QuestionAssessment]:
    return cast(
        Agent[None, QuestionAssessment],
        create_agent(
            get_chat_model(deployment or DEFAULT_LOCAL_CHAT_MODEL, cache=cache_model),
            name="chat_agent",
            output_type=(
                NativeOutput(QuestionAssessment, strict=True)
                if deployment is not None
                and deployment.kind is DeploymentKind.OPENROUTER
                and deployment.model.removeprefix("~").startswith("google/gemma-")
                else QuestionAssessment
            ),
            retries=0,
            instructions=CHAT_INSTRUCTIONS,
            capabilities=capabilities,
        ),
    )


class ChatSession:
    def __init__(
        self,
        original_question: str,
        *,
        chat_agent: Agent[None, QuestionAssessment],
        rewriter: Agent[None, QueryRewriteProposal] | None = None,
        retrieval: RetrievalCoordinator,
        coverage: CoverageDescription,
        relevant_collection_ids: tuple[str, ...],
        monthly_coverage: tuple[MonthlyCoverage, ...] = (),
        start_settings: ChatSessionSettings | None = None,
        as_of: datetime | None = None,
    ) -> None:
        self._as_of = _resolve_as_of(as_of)
        self._original_question = original_question
        self._agent = chat_agent
        self._retrieval = retrieval
        self._coverage = coverage
        self._relevant_collection_ids = relevant_collection_ids
        self._monthly_coverage = monthly_coverage
        self._usage = RunUsage()
        self._retrieval_result: EvidencePackage | EvidenceAssemblyFailure | None = None
        self.assessment: QuestionAssessment | None = None
        self.stage: Literal["assessment", "retrieval", "guidance"] = "assessment"
        self.chat_session_id = str(uuid4())
        self._preparation = (
            QuestionPreparation(
                original_question,
                rewriter=rewriter,
                assess_question_policy_and_coverage=self._assess,
                usage=self._usage,
                chat_session_id=self.chat_session_id,
            )
            if rewriter is not None
            else None
        )
        logfire.info(
            "chat_session.started",
            chat_session_id=self.chat_session_id,
            audit_schema_version=1,
            original_question=original_question,
            observed_at=datetime.now(UTC).isoformat(),
            as_of=self._as_of.isoformat(),
            current_date=self._as_of.date().isoformat(),
            coverage=coverage.model_dump(mode="json"),
            **(asdict(start_settings) if start_settings is not None else {}),
        )

    @property
    def as_of(self) -> datetime:
        """The session's fixed reference time, independent of source dates."""
        return self._as_of

    @property
    def retrieval_result(self) -> EvidencePackage | EvidenceAssemblyFailure | None:
        """Keep retrieved evidence inspectable when later guidance fails."""
        return self._retrieval_result

    async def _assess(self, rewrite: QueryRewriteProposal) -> QuestionAssessment:
        result = await self._agent.run(
            json.dumps(
                {
                    **_date_context(self._as_of),
                    "question": rewrite.question,
                    "coverage": self._coverage.model_dump(mode="json"),
                    "question_policy": QUESTION_POLICY,
                }
            ),
            usage=self._usage,
        )
        return result.output

    async def prepare(self) -> QuestionPreparationResult:
        assert self._preparation is not None
        rejections = self._preparation.rejections
        with logfire.span(
            "chat_session.correct" if rejections else "chat_session.prepare",
            chat_session_id=self.chat_session_id,
            audit_schema_version=1,
        ):
            if rejections:
                logfire.info(
                    "chat_session.rewrite_corrected",
                    chat_session_id=self.chat_session_id,
                    audit_schema_version=1,
                    proposal_attempt=len(rejections),
                    **rejections[-1].model_dump(exclude_none=True),
                )
            result = await self._preparation.prepare()
            if result.status != "awaiting_approval":
                self._log_usage()
            return result

    def reject(self, correction: str | None = None) -> RewriteRejection:
        assert self._preparation is not None
        return self._preparation.reject(correction)

    async def approve(self) -> RetrievalAnswer | EvidenceAssemblyFailure:
        assert self._preparation is not None
        with logfire.span(
            "chat_session.approve",
            chat_session_id=self.chat_session_id,
            audit_schema_version=1,
        ):
            rewrite = self._preparation.approve()
            logfire.info(
                "chat_session.rewrite_approved",
                chat_session_id=self.chat_session_id,
                audit_schema_version=1,
                proposal_attempt=len(self._preparation.rejections) + 1,
                approved_question=rewrite.question,
                relational=rewrite.relational,
            )
            try:
                return await self._answer(rewrite)
            finally:
                self._log_usage()

    async def run(
        self,
    ) -> RetrievalAnswer | EvidenceAssemblyFailure | QuestionAssessment:
        """Assess and search the submitted wording without a rewrite proposal."""
        with logfire.span(
            "chat_session.submit",
            chat_session_id=self.chat_session_id,
            audit_schema_version=2,
        ):
            try:
                proposal = QueryRewriteProposal(
                    question=self._original_question,
                    relational=True,
                )
                with logfire.span(
                    "chat_session.assessment",
                    chat_session_id=self.chat_session_id,
                    audit_schema_version=2,
                ) as span:
                    try:
                        assessment = self.assessment = await self._assess(proposal)
                    except Exception as error:
                        span.set_attributes(
                            {
                                "status": "failed",
                                "failure_kind": _guidance_failure_kind(error),
                                "diagnostic": "The Chat Agent could not assess the question.",
                            }
                        )
                        raise
                    span.set_attributes(assessment.model_dump(exclude_none=True))
                if assessment.status in {"declined", "needs_edit"}:
                    return assessment
                return await self._answer(
                    QueryRewrite(
                        **proposal.model_dump(),
                        assessment=assessment,
                    )
                )
            finally:
                self._log_usage()

    def _log_usage(self) -> None:
        logger.info(
            "chat_total_usage",
            extra={
                "event": "chat_total_usage",
                "requests": self._usage.requests,
                "input_tokens": self._usage.input_tokens,
                "output_tokens": self._usage.output_tokens,
            },
        )

    async def _answer(
        self, rewrite: QueryRewrite
    ) -> RetrievalAnswer | EvidenceAssemblyFailure:
        self.stage = "retrieval"
        package = await self._retrieval.run(
            rewrite,
            coverage=self._coverage,
            relevant_collection_ids=self._relevant_collection_ids,
            monthly_coverage=self._monthly_coverage,
            usage=self._usage,
            chat_session_id=self.chat_session_id,
        )
        self._retrieval_result = package
        if isinstance(package, EvidenceAssemblyFailure):
            return package
        self.stage = "guidance"
        return await generate_retrieval_answer(
            self._agent,
            package,
            original_question=self._original_question,
            chat_session_id=self.chat_session_id,
            usage=self._usage,
            as_of=self._as_of,
        )
