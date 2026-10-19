"""Measure retrieval and generate an answer to the fixed approved question."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_ai.usage import RunUsage
from pydantic_core import to_jsonable_python
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from knowledge_map.chat_presentation import project_source_guide, render_source_guide
from knowledge_map.chat_startup import chat_dependencies
from knowledge_map.config import document_store_path
from knowledge_map.core.chat import CHAT_INSTRUCTIONS, generate_retrieval_answer
from knowledge_map.core.fusion import fuse_candidates
from knowledge_map.jev.prompts import JEV_PROMPTS
from knowledge_map.schemas import ModelDeployment
from knowledge_map.schemas.query_preparation import QueryRewrite
from knowledge_map.schemas.retrieval import (
    EvidenceAssemblyFailure,
    EvidencePackage,
    FusedCandidate,
    NonemptyText,
    RetrievalAnswer,
    RetrievalRequest,
)

from ..data_set import LabelQuality
from ..deployment import as_deployment, default_model
from ..engine import EvaluationCaseLifecycle
from ..headline import CaseMean, HeadlineDefinition, Rate, Role
from ..retrieval_report import METRIC_VERSION
from .chat import (
    ChatFailure,
    capture_messages,
    chat_stage_observations,
    completed_answer,
)
from .registry import EvaluationTask, register

type Ids = Annotated[tuple[NonemptyText, ...], Field(min_length=1)]


class EvidenceRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: NonemptyText
    ids: Ids


class ReferenceAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    groups: Annotated[tuple[EvidenceRequirement, ...], Field(min_length=1)]


class RetrievalExpectation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    grain: Literal["article_chunk", "source_article"]
    relevant_ids: Ids
    answers: Annotated[tuple[ReferenceAnswer, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def requirements_name_relevant_evidence(self) -> Self:
        relevant = set(self.relevant_ids)
        if len(relevant) != len(self.relevant_ids):
            raise ValueError("relevant evidence IDs must be distinct")
        required = {
            id for answer in self.answers for g in answer.groups for id in g.ids
        }
        if required != relevant:
            raise ValueError("answer requirements must cover exactly the relevant IDs")
        return self


class RetrievalMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family: NonemptyText
    scope_note: NonemptyText
    reference_artifact: NonemptyText
    reference_sha256: NonemptyText
    reference_checked_at: NonemptyText
    annotation_guideline: NonemptyText
    label_quality: Literal["silver"] = "silver"
    annotator: Literal["Codex"] = "Codex"


class RetrievalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: EvidencePackage | EvidenceAssemblyFailure | None = None
    answer: RetrievalAnswer | None = None
    rendered_text: str | None = None
    chat_session_id: str | None = None
    fused: tuple[FusedCandidate, ...] = ()
    failure: ChatFailure | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    messages: list[dict[str, Any]] = Field(default_factory=list)


def build_task(model: str | ModelDeployment, data_set: Any) -> Any:
    del data_set
    deployment = as_deployment(model)

    async def retrieve(rewrite: QueryRewrite) -> RetrievalOutput:
        # These authored evaluation inputs stand in for approved questions.
        # Reference labels never enter a retrieval or model request.
        RetrievalRequest(rewrite=rewrite)
        output = RetrievalOutput()
        usage = RunUsage()
        stage = "startup"
        try:
            async with chat_dependencies(
                chat_deployment=deployment,
                capabilities=(capture_messages(output.messages),),
            ) as dependencies:
                output.settings = to_jsonable_python(
                    dataclasses.asdict(dependencies.start_settings)
                )
                stage = "retrieval"
                output.chat_session_id = str(uuid4())
                output.result = await dependencies.retrieval.run(
                    rewrite,
                    coverage=dependencies.coverage,
                    relevant_collection_ids=("calmatters",),
                    chat_session_id=output.chat_session_id,
                    usage=usage,
                )
                # Reuse production fusion on the complete execution, including
                # candidates omitted by Evidence Assembly's context budget.
                output.fused = fuse_candidates(
                    output.result.execution,
                    config=dependencies.start_settings.fusion_settings,
                )
                if isinstance(output.result, EvidencePackage):
                    stage = "guidance"
                    output.answer = await generate_retrieval_answer(
                        dependencies.chat_agent,
                        output.result,
                        original_question=rewrite.question,
                        chat_session_id=output.chat_session_id,
                        usage=usage,
                    )
                    stage = "rendering"
                    output.rendered_text = render_source_guide(
                        project_source_guide(
                            output.answer,
                            question=rewrite.question,
                            search_scope=None,
                            story_db_path=document_store_path(),
                        )
                    )
                stage = "cleanup"
        except Exception as error:  # noqa: BLE001 - Keep unavailable cases in the population.
            output.failure = ChatFailure(
                stage=stage,
                kind="execution",
                exception_type=type(error).__name__,
                diagnostic=f"RAG evaluation could not complete {stage}.",
            )
        return output

    return retrieve


class RetrievalCaseLifecycle(EvaluationCaseLifecycle):
    async def prepare_context(self, ctx: EvaluatorContext) -> EvaluatorContext:
        ctx = await super().prepare_context(ctx)
        ctx.attributes["chat_session_id"] = ctx.output.chat_session_id
        ctx.attributes["retrieval_metric_version"] = METRIC_VERSION
        ctx.attributes["stage_observations"] = chat_stage_observations(ctx)
        return ctx


def ranked_ids(candidates: Any, grain: str) -> tuple[str, ...]:
    """Order unique chunks by their best rank before projecting article IDs.

    Several chunks from one article consume several slots in the retrieval
    budget. Deduplicating articles before applying k would overstate coverage.
    """
    ordered = sorted(
        candidates,
        key=lambda c: (c.ranking.rank if hasattr(c, "ranking") else c.rank, c.chunk_id),
    )
    chunks = {c.chunk_id: c for c in reversed(ordered)}
    return tuple(
        c.chunk_id if grain == "article_chunk" else c.source_article_id
        for c in sorted(
            chunks.values(),
            key=lambda c: (
                c.ranking.rank if hasattr(c, "ranking") else c.rank,
                c.chunk_id,
            ),
        )
    )


def retrieval_scores(
    found: tuple[str, ...],
    expected: RetrievalExpectation,
    *,
    prefix: str,
    ks: tuple[int, ...],
) -> dict[str, EvaluationReason]:
    relevant = set(expected.relevant_ids)
    scores = {}
    for k in ks:
        selected = set(found[:k])
        missing = sorted(relevant - selected)
        scores[f"{prefix}_recall_at_{k}"] = EvaluationReason(
            value=len(relevant & selected) / len(relevant),
            reason=f"{expected.grain}; {len(missing)} missing reference IDs: {missing[:10]}",
        )
        matches = sum(id in relevant for id in found[:k])
        scores[f"{prefix}_precision_at_{k}"] = EvaluationReason(
            value=matches / k,
            reason=(
                f"Reference-based {expected.grain} precision: {matches}/{k} chunk slots "
                "match the reference set. Missing slots count as zero; "
                "unlisted chunks may still be useful."
            ),
        )
        complete = sum(
            all(selected.intersection(g.ids) for g in answer.groups)
            for answer in expected.answers
        )
        scores[f"{prefix}_complete_evidence_at_{k}"] = EvaluationReason(
            value=complete / len(expected.answers),
            reason=f"All evidence groups found for {complete}/{len(expected.answers)} reference answers.",
        )
    scores[f"{prefix}_reciprocal_rank"] = EvaluationReason(
        value=next(
            (1 / rank for rank, id in enumerate(found[:50], 1) if id in relevant), 0.0
        ),
        reason=f"First relevant {expected.grain} within 50 unique Article Chunks.",
    )
    return scores


@dataclass
class RetrievedReferenceEvidence(Evaluator):
    ks: tuple[int, ...] = (1, 5, 10, 50)

    def __post_init__(self) -> None:
        if not self.ks or any(type(k) is not int or not 1 <= k <= 50 for k in self.ks):
            raise ValueError("retrieval cutoffs must be integers between 1 and 50")

    def evaluate(self, ctx: EvaluatorContext) -> dict[str, EvaluationReason]:
        expected = ctx.expected_output
        if expected is None:
            raise ValueError("retrieval cases require reference evidence labels")
        output = ctx.output
        execution = output.result.execution if output.result is not None else None
        scores = {}
        expected_branches = (
            execution.expected_branches
            if execution is not None
            else RetrievalRequest(
                rewrite=ctx.inputs, structural_reporting=True
            ).expected_branches
        )
        for branch in expected_branches:
            candidates = (
                execution.evidence_by_branch.get(branch, ()) if execution else ()
            )
            scores.update(
                retrieval_scores(
                    ranked_ids(candidates, expected.grain),
                    expected,
                    prefix=branch.value,
                    ks=self.ks,
                )
            )
            scores[f"{branch.value}_completed"] = EvaluationReason(
                value=execution is not None and branch in execution.evidence_by_branch,
                reason="Successful empty branches completed; failed branches receive zero retrieval scores.",
            )
        scores.update(
            retrieval_scores(
                ranked_ids(output.fused, expected.grain),
                expected,
                prefix="fused",
                ks=self.ks,
            )
        )
        package = output.result if isinstance(output.result, EvidencePackage) else None
        context_ids = ranked_ids(
            [p.candidate for s in package.sources for p in s.passages]
            if package
            else (),
            expected.grain,
        )
        # The final context has its own passage budget, not a fixed top-k.
        context_k = max(1, len(context_ids))
        context_scores = retrieval_scores(
            context_ids,
            expected,
            prefix="context",
            ks=(context_k,),
        )
        scores["context_recall"] = context_scores[f"context_recall_at_{context_k}"]
        scores["context_complete_evidence"] = context_scores[
            f"context_complete_evidence_at_{context_k}"
        ]
        scores["evidence_assembled"] = EvaluationReason(value=package is not None)
        scores["retrieval_attempt_completed"] = EvaluationReason(
            value=output.result is not None
        )
        scores["answer_generated"] = EvaluationReason(
            value=output.answer is not None,
            reason="A validated Chat Agent answer was produced; this does not judge its relevance or faithfulness.",
        )
        return scores


# A retrieval headline means what the case scores it averages mean, so each
# retrieval metric version names its own headline version.  A new metric
# version fails here until a headline version is added for it.
HEADLINE_VERSIONS = {"unique-chunk-budget-v2": "retrieval-v1"}

# Each question is one information need, so every row is a per-question mean.
# The rows are outcomes a reader would observe; branch breakdowns stay in the
# RAG reviewer's case views.
RETRIEVAL_HEADLINE = HeadlineDefinition(
    version=HEADLINE_VERSIONS[METRIC_VERSION],
    measures=(
        CaseMean(score="fused_recall_at_10", role=Role.PRIMARY),
        Rate.operational("completed_answer_rate", completed_answer, Role.HEADLINE),
        CaseMean(score="fused_recall_at_5", role=Role.HEADLINE),
        CaseMean(score="fused_reciprocal_rank", role=Role.HEADLINE),
        CaseMean(score="fused_complete_evidence_at_10", role=Role.HEADLINE),
        CaseMean(score="context_recall", role=Role.HEADLINE),
        CaseMean(score="context_complete_evidence", role=Role.HEADLINE),
    ),
)

RETRIEVAL_TASK = register(
    EvaluationTask(
        name="retrieval",
        input_type=QueryRewrite,
        output_type=RetrievalExpectation,
        metadata_type=RetrievalMetadata,
        label_quality=LabelQuality.SILVER,
        build=build_task,
        evaluators=(RetrievedReferenceEvidence(),),
        case_lifecycle=RetrievalCaseLifecycle,
        default_model=default_model(),
        prompts=lambda: {**JEV_PROMPTS, "chat_agent": CHAT_INSTRUCTIONS},
        headline=RETRIEVAL_HEADLINE,
    )
)
