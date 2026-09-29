"""Exercise the production Chat Session and retain evidence for human review."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_core import to_jsonable_python
from pydantic_evals.evaluators import EvaluatorContext

from knowledge_map.adapters.structural import STRUCTURAL_INSTRUCTIONS
from knowledge_map.chat_presentation import render_answer
from knowledge_map.chat_startup import chat_dependencies, new_chat_session
from knowledge_map.core.chat import CHAT_INSTRUCTIONS, QUESTION_POLICY
from knowledge_map.core.question_preparation import (
    QUERY_REWRITER_INSTRUCTIONS,
    model_failure_kind,
)
from knowledge_map.schemas import ModelDeployment
from knowledge_map.schemas.query_preparation import (
    AwaitingQueryApproval,
    QuestionPreparationResult,
)
from knowledge_map.schemas.retrieval import (
    CoverageDescription,
    EvidenceAssemblyFailure,
    EvidencePackage,
    RetrievalAnswer,
)
from knowledge_map.utils.telemetry import project_url

from ..data_set import LabelQuality
from ..deployment import as_deployment, default_model
from ..engine import EvaluationCaseLifecycle
from .registry import EvaluationTask, register


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)


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

    No field claims that an answer is correct. The first proposal is approved
    mechanically, so reviewers must inspect whether it preserved the question.
    """

    model_config = ConfigDict(extra="forbid")

    question: str
    approval_mode: Literal["approve_first_proposal"] = "approve_first_proposal"
    chat_session_id: str | None = None
    preparation: QuestionPreparationResult | None = None
    answer: RetrievalAnswer | EvidenceAssemblyFailure | None = None
    retrieval: EvidencePackage | EvidenceAssemblyFailure | None = None
    rendered_text: str | None = None
    failure: ChatFailure | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    coverage: CoverageDescription | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)


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
        output = ChatOutput(question=case_input.question)
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
                session = new_chat_session(case_input.question, dependencies)
                output.chat_session_id = session.chat_session_id
                stage = "preparation"
                output.preparation = await session.prepare()
                if isinstance(output.preparation, AwaitingQueryApproval):
                    stage = "retrieval_and_guidance"
                    try:
                        output.answer = await session.approve()
                    finally:
                        if output.answer is None:
                            output.retrieval = session.retrieval_result
                    stage = "rendering"
                    output.rendered_text = render_answer(output.answer)
                else:
                    output.rendered_text = output.preparation.message
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
        ctx.attributes["stage_observations"] = [
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
        return ctx


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
        prompts=lambda: {
            "query_rewriter": QUERY_REWRITER_INSTRUCTIONS,
            "chat_agent": CHAT_INSTRUCTIONS,
            "question_policy": QUESTION_POLICY,
            **STRUCTURAL_INSTRUCTIONS,
        },
    )
)
