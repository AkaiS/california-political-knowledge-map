"""Exercise the production Chat Session and retain evidence for human review."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from datetime import UTC, datetime
from statistics import fmean
from typing import Any, Literal
from urllib.parse import quote

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
)
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_core import to_jsonable_python
from pydantic_evals.evaluators import EvaluatorContext
from pydantic_evals.reporting import ReportCase, ReportCaseFailure

from knowledge_map.chat_presentation import (
    ChatSessionOutcome,
    ChatSessionStageFailure,
    guide_collections,
    project_source_guide,
    render_source_guide,
)
from knowledge_map.chat_startup import chat_dependencies, new_chat_session
from knowledge_map.config import document_store_path
from knowledge_map.core.chat import CHAT_INSTRUCTIONS, QUESTION_POLICY
from knowledge_map.core.question_preparation import model_failure_kind
from knowledge_map.jev.prompts import JEV_PROMPTS
from knowledge_map.schemas import ModelDeployment
from knowledge_map.schemas.query_preparation import (
    QuestionAssessment,
    QuestionPreparationResult,
)
from knowledge_map.schemas.retrieval import (
    CoverageDescription,
    EvidenceAssemblyFailure,
    EvidencePackage,
    RetrievalAnswer,
)
from knowledge_map.schemas.source_guides import SourceGuide
from knowledge_map.utils.telemetry import project_url

from ..data_set import LabelQuality
from ..deployment import as_deployment, default_model
from ..engine import EvaluationCaseLifecycle
from ..headline import (
    COMPLETED_ANSWER_RATE,
    DECLINED_RATE,
    Aggregation,
    HeadlineDefinition,
    Quantile,
    Rate,
    Role,
    Unavailable,
)
from .registry import EvaluationTask, register


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    as_of: AwareDatetime | None = None


class ChatMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    source_case_id: str | None = None
    family: str
    cohort: Literal["populated_graph", "declined_control", "deferred_control"]
    scope_note: str
    grounding: str | None = None
    reference_artifact: str | None = None


class ChatFailure(BaseModel):
    stage: str
    kind: str
    exception_type: str
    diagnostic: str


class ChatOutput(BaseModel):
    """A completed attempt can contain a failed stage or a declined question.

    No field claims that an answer is correct. Historical approval runs retain
    their original mode; new runs assess and retrieve the submitted question.
    """

    model_config = ConfigDict(extra="forbid")

    question: str
    approval_mode: Literal["approve_first_proposal", "direct_question"] = (
        "approve_first_proposal"
    )
    chat_session_id: str | None = None
    as_of: AwareDatetime | None = None
    preparation: QuestionPreparationResult | None = None
    assessment: QuestionAssessment | None = None
    guide: SourceGuide | None = None
    answer: RetrievalAnswer | EvidenceAssemblyFailure | None = None
    retrieval: EvidencePackage | EvidenceAssemblyFailure | None = None
    rendered_text: str | None = None
    failure: ChatFailure | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    coverage: CoverageDescription | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)

    @field_serializer("answer", "retrieval")
    def serialize_retrieval_result(
        self, value: RetrievalAnswer | EvidenceAssemblyFailure | EvidencePackage | None
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        return compact_retrieval_for_report(value.model_dump(mode="json"))


def compact_retrieval_for_report(document: dict[str, Any]) -> dict[str, Any]:
    """Keep the full result in memory and bound its full-text report payload.

    Selected Grounding Evidence retains its own candidate contributions, even
    when a contribution falls below the branch-list cutoff.
    """
    evidence = document.get("evidence", document)
    execution = evidence.get("execution", document.get("execution"))
    if execution is None:
        return document
    outcomes = execution.get("outcomes", ())
    dense = next(
        (
            outcome
            for outcome in outcomes
            if outcome["branch"] == "dense" and outcome["status"] == "succeeded"
        ),
        None,
    )
    keep_count = len(dense["candidates"]) if dense is not None else 0
    full_text = next(
        (
            outcome
            for outcome in outcomes
            if outcome["branch"] == "full_text" and outcome["status"] == "succeeded"
        ),
        None,
    )
    if full_text is None:
        return document
    if "candidate_summary" in full_text:
        return document

    candidates = sorted(
        full_text["candidates"],
        key=lambda candidate: (candidate["ranking"]["rank"], candidate["chunk_id"]),
    )
    unlisted = candidates[keep_count:]
    scores = [
        candidate["ranking"]["score"]
        for candidate in candidates
        if candidate["ranking"]["score"] is not None
    ]
    unlisted_scores = [
        candidate["ranking"]["score"]
        for candidate in unlisted
        if candidate["ranking"]["score"] is not None
    ]
    unlisted_ranks = [candidate["ranking"]["rank"] for candidate in unlisted]
    full_text["candidates"] = candidates[:keep_count]
    full_text["candidate_summary"] = {
        "total_retrieved": len(candidates),
        "dense_retrieved": keep_count,
        "retained_count": len(full_text["candidates"]),
        "unlisted_count": len(unlisted),
        "scored_count": len(scores),
        "unlisted_scored_count": len(unlisted_scores),
        "all_avg_score": fmean(scores) if scores else None,
        "unlisted_avg_score": fmean(unlisted_scores) if unlisted_scores else None,
        "unlisted_min_score": min(unlisted_scores, default=None),
        "unlisted_max_score": max(unlisted_scores, default=None),
        "unlisted_rank_min": min(unlisted_ranks, default=None),
        "unlisted_rank_max": max(unlisted_ranks, default=None),
    }
    return document


def capture_messages(records: list[dict[str, Any]]) -> Hooks:
    """Keep each model exchange locally, including retries and failed requests.

    The hook belongs to one case's dependencies. Concurrent structural calls
    append distinct records; the timestamps describe overlap. Logfire's global
    content policy is independent of this local evaluation artifact.
    """

    hooks = Hooks()

    @hooks.on.model_request
    async def record_request(ctx, *, request_context, handler):
        record = {
            "component": ctx.agent.name if ctx.agent else "unknown",
            "run_id": ctx.run_id,
            "request_index": ctx.run_step,
            "status": "started",
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": None,
            "messages": json.loads(
                ModelMessagesTypeAdapter.dump_json(request_context.messages)
            ),
            "request_parameters": to_jsonable_python(
                dataclasses.asdict(request_context.model_request_parameters)
            ),
            "model_settings": to_jsonable_python(request_context.model_settings),
        }
        records.append(record)
        try:
            response = await handler(request_context)
        except BaseException as error:
            record["status"] = "failed"
            record["exception_type"] = type(error).__name__
            raise
        else:
            record["messages"].extend(
                json.loads(ModelMessagesTypeAdapter.dump_json([response]))
            )
            record["status"] = "succeeded"
            return response
        finally:
            record["finished_at"] = datetime.now(UTC).isoformat()

    return hooks


def build_task(model: str | ModelDeployment, data_set: Any) -> Any:
    del data_set
    deployment = as_deployment(model)

    async def answer_question(case_input: ChatInput) -> ChatOutput:
        output = ChatOutput(
            question=case_input.question, approval_mode="direct_question"
        )
        stage = "startup"
        try:
            async with chat_dependencies(
                chat_deployment=deployment,
                capabilities=(capture_messages(output.messages),),
            ) as dependencies:
                output.settings = to_jsonable_python(
                    dataclasses.asdict(dependencies.start_settings)
                )
                output.coverage = dependencies.coverage
                session = new_chat_session(
                    case_input.question, dependencies, as_of=case_input.as_of
                )
                output.chat_session_id = session.chat_session_id
                output.as_of = session.as_of
                search_scope = guide_collections(dependencies.coverage)

                def reader_guide(outcome: ChatSessionOutcome) -> SourceGuide:
                    return project_source_guide(
                        outcome,
                        question=case_input.question,
                        search_scope=search_scope,
                        story_db_path=document_store_path(),
                    )

                stage = "retrieval_and_guidance"
                try:
                    result = await session.run()
                except Exception:
                    # Reviewers see the failed guide a reader would see for
                    # the stage the Chat Session reached.
                    output.guide = reader_guide(
                        ChatSessionStageFailure(
                            stage=session.stage, assessment=session.assessment
                        )
                    )
                    raise
                finally:
                    output.assessment = session.assessment
                    output.retrieval = session.retrieval_result
                if not isinstance(result, QuestionAssessment):
                    output.answer = result
                    output.retrieval = None
                    stage = "rendering"
                output.guide = reader_guide(result)
                output.rendered_text = (
                    result.explanation
                    if isinstance(result, QuestionAssessment)
                    else render_source_guide(output.guide)
                )
                stage = "cleanup"
        except Exception as error:  # noqa: BLE001 - Preserve a failed case for review.
            # A bad answer, unavailable dependency, or failed model request is
            # the case to inspect. Keep its partial trail in the report.
            output.failure = ChatFailure(
                stage=stage,
                kind="validation"
                if isinstance(error, ValidationError)
                else model_failure_kind(error),
                exception_type=type(error).__name__,
                diagnostic=f"Chat evaluation could not complete {stage}.",
            )
        return output

    return answer_question


def chat_stage_observations(ctx: EvaluatorContext) -> list[dict[str, Any]]:
    return [
        {
            "name": span.name,
            "trace_id": f"{span.trace_id:032x}",
            "span_id": f"{span.span_id:016x}",
            "parent_span_id": f"{span.parent_span_id:016x}"
            if span.parent_span_id is not None
            else None,
            "started_at": span.start_timestamp.isoformat(),
            "finished_at": span.end_timestamp.isoformat(),
            "attributes": span.attributes,
        }
        for span in ctx.span_tree
        if span.name.startswith("chat_session.")
    ]


class ChatCaseLifecycle(EvaluationCaseLifecycle):
    async def prepare_context(self, ctx: EvaluatorContext) -> EvaluatorContext:
        ctx = await super().prepare_context(ctx)
        output = ctx.output
        if not isinstance(output, ChatOutput):
            return ctx
        ctx.attributes["chat_session_id"] = output.chat_session_id
        project = project_url()
        ctx.attributes["chat_session_url"] = (
            f"{project}?q="
            + quote(f"attributes->>'chat_session_id' = '{output.chat_session_id}'")
            if project and output.chat_session_id
            else None
        )
        ctx.attributes["stage_observations"] = chat_stage_observations(ctx)
        return ctx


def completed_answer(case: ReportCase | ReportCaseFailure) -> bool:
    """A rendered Source Guide built on a guidance answer, whatever its introduction.

    Failed Evidence Assembly is not an answer.  An answer whose introduction is
    null still guided the reader to sources.
    """

    return (
        isinstance(case, ReportCase)
        and bool(case.output.rendered_text)
        and isinstance(case.output.answer, RetrievalAnswer)
    )


def _question_status(
    status: Literal["declined", "deferred", "needs_edit"],
) -> Callable[[ReportCase | ReportCaseFailure], bool]:
    """Whether the question's recorded assessment, or else its preparation, says ``status``.

    A historical approval run records only its question preparation.
    """

    def has_status(case: ReportCase | ReportCaseFailure) -> bool:
        if not isinstance(case, ReportCase):
            return False
        decision = case.output.assessment or case.output.preparation
        return decision is not None and decision.status == status

    return has_status


def _task_duration(case: ReportCase) -> float:
    return case.task_duration


CHAT_HEADLINE = HeadlineDefinition(
    version="chat-v1",
    measures=(
        Unavailable(
            metric="answer_quality",
            aggregation=Aggregation.RATE,
            role=Role.PRIMARY,
            reason="Unlabeled Set: no quality metric",
        ),
        Rate.operational(COMPLETED_ANSWER_RATE, completed_answer, Role.HEADLINE),
        Rate.operational(DECLINED_RATE, _question_status("declined"), Role.HEADLINE),
        Rate.operational("deferred_rate", _question_status("deferred"), Role.HEADLINE),
        Rate.operational(
            "needs_edit_rate", _question_status("needs_edit"), Role.HEADLINE
        ),
        Quantile(
            metric="task_duration_p50",
            q=0.5,
            of=_task_duration,
            role=Role.HEADLINE,
        ),
        Quantile(
            metric="task_duration_p95",
            q=0.95,
            of=_task_duration,
            role=Role.HEADLINE,
        ),
    ),
)


CHAT_TASK = register(
    EvaluationTask(
        name="chat",
        input_type=ChatInput,
        output_type=ChatOutput,
        metadata_type=ChatMetadata,
        label_quality=LabelQuality.UNLABELED,
        build=build_task,
        evaluators=(),
        default_model=default_model(),
        case_lifecycle=ChatCaseLifecycle,
        headline=CHAT_HEADLINE,
        prompts=lambda: {
            "chat_agent": CHAT_INSTRUCTIONS,
            "question_policy": QUESTION_POLICY,
            **JEV_PROMPTS,
        },
    )
)
