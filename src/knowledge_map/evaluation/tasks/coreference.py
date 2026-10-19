"""Coreference Resolution as an evaluated task.

Cases come from `evals/silver/coreference.yaml`, authored elsewhere and only
read here.  It is silver, not gold: labeled by `gpt-5.6-sol`, so a run
measures agreement with that model and a case both models get wrong scores
as a pass.

Two tasks read that one file.  `coreference` runs the whole loop;
`coreference_annotator` runs the annotator alone.  Compare their reports to
see what the Critic rounds are worth.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals.evaluators import Evaluator, EvaluatorContext
from pydantic_evals.reporting import ReportCase

from knowledge_map.adapters.coreference import (
    ANNOTATOR_INSTRUCTIONS,
    CRITIC_INSTRUCTIONS,
    CoreferenceResolutionError,
    MentionSpanIdentity,
    annotate_coreferences_run,
    get_annotator_agent,
    get_critic_agent,
    resolve_coreferences_run,
)
from knowledge_map.config import settings
from knowledge_map.schemas import (
    CoreferenceResolutionRun,
    MentionSpan,
    MentionSpanOutcome,
    ModelDeployment,
)

from ..data_set import LabelQuality
from ..deployment import as_deployment, default_model
from ..headline import (
    CaseMean,
    Counts,
    HeadlineDefinition,
    Measure,
    Pooled,
    Role,
    SetAgreement,
    detection_counts,
)
from ..scoring import UNSCORED, detection_scores, f1
from .registry import EvaluationTask, register


class CoreferenceInput(BaseModel):
    """One Story as the Coreference Annotator sees it.

    The annotator is shown `content` alone; `url` and `title` are carried
    so a report names something a person can open.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    content: str


class CoreferenceExpectation(BaseModel):
    """The silver Mention Spans retained for one Story."""

    model_config = ConfigDict(extra="forbid")

    mention_spans: list[MentionSpan]


class CoreferenceOutput(BaseModel):
    """What one resolution attempt produced, including its own failure.

    A failed resolution is scored as a zero rather than raised, so it stays
    in the population.
    """

    model_config = ConfigDict(extra="forbid")

    mention_spans: list[MentionSpan] = Field(default_factory=list)
    outcomes: list[MentionSpanOutcome] = Field(default_factory=list)
    """Every Mention Span the run ruled on, with the stage that ruled.

    Read by `RejectedOnlyTheWrongMentionSpans` to score the Critic.
    """
    failure_type: str | None = None
    retry_count: int = 0
    discarded_proportion: float = 0.0


class CoreferenceSilverMetadata(BaseModel):
    """Source and model provenance for one silver-labeled Story.

    ``annotation_guideline`` names the guideline the labeling model was
    given, which is what makes one case's judgment calls comparable to
    another's.
    """

    model_config = ConfigDict(extra="forbid")

    source_table: Literal["stories"]
    story_id: int
    label_quality: Literal["silver"]
    annotator_model: str
    annotation_guideline: str


def _output_from_run(run: CoreferenceResolutionRun) -> CoreferenceOutput:
    """Carry a completed run into the shape the evaluators read."""

    return CoreferenceOutput(
        mention_spans=run.surviving_spans,
        outcomes=run.outcomes,
        failure_type=run.failure_type,
        retry_count=run.retry_count,
        discarded_proportion=run.discarded_proportion,
    )


def _output_from_failure(error: CoreferenceResolutionError) -> CoreferenceOutput:
    """Carry a failed run into the same shape, keeping what it reached.

    Outcomes travel too, so a run that failed because the Critic rejected
    everything is still scored on those rejections.
    """

    failed = error.resolution_run
    if failed is None:
        return CoreferenceOutput(failure_type=error.failure_type)
    return CoreferenceOutput(
        outcomes=failed.outcomes,
        failure_type=error.failure_type,
        retry_count=failed.retry_count,
        discarded_proportion=failed.discarded_proportion,
    )


def build_task(model: str | ModelDeployment, data_set: Any) -> Any:
    """Return the callable one case is run through, bound to a deployment.

    `data_set` is in the signature for the registry's uniform call and goes
    unused; nothing here few-shots.  The callable is synchronous, which
    Pydantic Evals runs in a worker thread, so `--max-concurrency` still
    parallelizes.
    """

    del data_set

    deployment = as_deployment(model)
    annotator_agent = get_annotator_agent(deployment)
    critic_agent = get_critic_agent(deployment)

    def resolve(case_input: CoreferenceInput) -> CoreferenceOutput:
        try:
            run = resolve_coreferences_run(
                case_input.content,
                annotator_agent=annotator_agent,
                critic_agent=critic_agent,
                max_critic_rounds=settings.coreference.max_critic_rounds,
                deployment=deployment,
            )
        except CoreferenceResolutionError as error:
            return _output_from_failure(error)
        return _output_from_run(run)

    return resolve


def build_annotator_task(model: str | ModelDeployment, data_set: Any) -> Any:
    """Return the callable for one annotator-only case, bound to a deployment."""

    del data_set

    deployment = as_deployment(model)
    annotator_agent = get_annotator_agent(deployment)

    def annotate(case_input: CoreferenceInput) -> CoreferenceOutput:
        try:
            run = annotate_coreferences_run(
                case_input.content,
                annotator_agent=annotator_agent,
                deployment=deployment,
            )
        except CoreferenceResolutionError as error:
            return _output_from_failure(error)
        return _output_from_run(run)

    return annotate


def normalize_entity_name(name: str) -> str:
    """Fold case and collapse whitespace, and change nothing else.

    A shortened name stays a mismatch here; `MatchedTheSilverClustering`
    reads no names and catches it instead.
    """

    return " ".join(name.split()).casefold()


def entity_by_identity(
    mention_spans: Sequence[MentionSpan],
) -> dict[MentionSpanIdentity, str]:
    """Index one entity name per text location, last one winning.

    Last-wins matches `ResolutionState`, so scoring agrees with the run it
    is scoring.
    """

    return {
        MentionSpanIdentity.of(span): normalize_entity_name(span.canonical_entity_name)
        for span in mention_spans
    }


class FoundTheSilverMentionSpans(Evaluator):
    """The same *mentions* were found, whatever they were said to refer to.

    Detection alone, keyed by text location.  Read recall first: a mention
    the annotator never proposed is gone from the graph, while a spurious
    one costs only a wrong substitution.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float]:
        return detection_scores(
            _mention_spans(ctx.expected_output), _mention_spans(ctx.output), "span"
        )


def _mention_spans(
    answer: CoreferenceExpectation | CoreferenceOutput,
) -> set[MentionSpanIdentity]:
    return set(entity_by_identity(answer.mention_spans))


class AgreedOnTheCanonicalEntity(Evaluator):
    """Of the mentions both found, how many carry the same entity name.

    Conditional on detection: read it as "when it saw the mention, did it
    name the right entity".  Scores nothing, rather than 0, when the two
    sets share no location.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float]:
        agreement = _entity_agreement(ctx)
        if agreement is None:
            return UNSCORED
        agreed, shared = agreement
        return {"entity_accuracy": agreed / shared}


def _entity_agreement(case: EvaluatorContext | ReportCase) -> tuple[int, int] | None:
    """Mentions both sides found that carry the same entity name, of all shared.

    ``None`` when the two share no location, so there is nothing to agree on.
    """

    expected_entities = entity_by_identity(case.expected_output.mention_spans)
    found_entities = entity_by_identity(case.output.mention_spans)
    shared = expected_entities.keys() & found_entities.keys()
    if not shared:
        return None
    agreed = sum(expected_entities[key] == found_entities[key] for key in shared)
    return agreed, len(shared)


class MatchedTheSilverClustering(Evaluator):
    """The same *partition* of mentions, whatever the clusters were called.

    B-cubed over the locations both sides found.  Blind to names, so it
    catches only two people merged into one cluster or one person split
    across two; a mere naming choice is `AgreedOnTheCanonicalEntity`'s
    miss, not this one's.  Returns `None` on an empty intersection.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float]:
        counts = _cluster_counts(ctx)
        if not counts.precision_denominator:
            return UNSCORED
        precision = counts.precision_numerator / counts.precision_denominator
        recall = counts.recall_numerator / counts.recall_denominator
        return {
            "cluster_precision": precision,
            "cluster_recall": recall,
            "cluster_f1": f1(precision, recall),
        }


def _cluster_counts(case: EvaluatorContext | ReportCase) -> Counts:
    """B-cubed credit over the locations both sides found.

    Each shared mention earns precision credit for the share of its found
    cluster that silver also groups with it, and recall credit for the share
    of its silver cluster the model also grouped with it; both are counted
    over the shared mentions.  No shared location contributes zero.
    """

    expected_entities = entity_by_identity(case.expected_output.mention_spans)
    found_entities = entity_by_identity(case.output.mention_spans)
    shared = sorted(
        expected_entities.keys() & found_entities.keys(),
        key=lambda key: (key.sentence_label, key.mention_text, key.occurrence),
    )
    expected_clusters = _clusters(shared, expected_entities)
    found_clusters = _clusters(shared, found_entities)

    precision = 0.0
    recall = 0.0
    for key in shared:
        expected_cluster = expected_clusters[expected_entities[key]]
        predicted = found_clusters[found_entities[key]]
        overlap = len(expected_cluster & predicted)
        precision += overlap / len(predicted)
        recall += overlap / len(expected_cluster)
    return Counts(
        precision_numerator=precision,
        precision_denominator=len(shared),
        recall_numerator=recall,
        recall_denominator=len(shared),
    )


def _clusters(
    keys: Sequence[MentionSpanIdentity],
    entity_by_key: Mapping[MentionSpanIdentity, str],
) -> dict[str, set[MentionSpanIdentity]]:
    """Group ``keys`` by the entity each is assigned to."""

    grouped: dict[str, set[MentionSpanIdentity]] = {}
    for key in keys:
        grouped.setdefault(entity_by_key[key], set()).add(key)
    return grouped


class ResolvedWithoutFailing(Evaluator):
    """The run produced Mention Spans instead of raising.

    Read alongside the other three to tell a run that failed outright from
    one that answered badly; both score zero there.
    """

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output.failure_type is None


class RejectedOnlyTheWrongMentionSpans(Evaluator):
    """What the Coreference Critic's rejections were actually worth.

    Scored from the run's own outcomes against silver, one decision per
    location silver also annotated; locations silver skipped are not
    counted against the Critic.  Outcomes are last-wins, so these are net
    decisions: a rejection the annotator repaired cost a round, not an
    answer.

    Scores nothing when nothing was judgeable, which is every
    `coreference_annotator` run, so this can sit on both tasks.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float]:
        decisions = _critic_decisions(ctx)
        return {
            name: numerator / denominator
            for name, (numerator, denominator) in decisions.items()
        } or UNSCORED


_REJECTION_PRECISION = "critic_rejection_precision"
_REJECTION_RECALL = "critic_rejection_recall"
_KEPT_CORRECT_SPANS = "critic_kept_correct_spans"


def _critic_decisions(case: EvaluatorContext) -> dict[str, tuple[int, int]]:
    """Each Critic score's numerator and denominator over the judged decisions.

    A score is absent when the case had no decision it could be judged on.
    """

    silver = entity_by_identity(case.expected_output.mention_spans)

    # (the span was correct, the Critic rejected it)
    judged: list[tuple[bool, bool]] = []
    for outcome in case.output.outcomes:
        if outcome.stage != "critic":
            continue
        expected_entity = silver.get(MentionSpanIdentity.of(outcome.mention_span))
        if expected_entity is None:
            continue
        judged.append(
            (
                expected_entity
                == normalize_entity_name(outcome.mention_span.canonical_entity_name),
                outcome.outcome == "rejected",
            )
        )

    rejected = [correct for correct, was_rejected in judged if was_rejected]
    wrong = [was_rejected for correct, was_rejected in judged if not correct]
    right = [was_rejected for correct, was_rejected in judged if correct]

    fractions: dict[str, tuple[int, int]] = {}
    if rejected:
        # Of what it threw away, how much deserved it.
        fractions[_REJECTION_PRECISION] = (
            sum(not correct for correct in rejected),
            len(rejected),
        )
    if wrong:
        # Of the mistakes it was shown, how many it caught.
        fractions[_REJECTION_RECALL] = (sum(wrong), len(wrong))
    if right:
        # Of the correct spans it was shown, how many it left alone.
        # The complement of a false-rejection rate, so that higher is
        # better here as everywhere else in the report.
        fractions[_KEPT_CORRECT_SPANS] = (
            sum(not was_rejected for was_rejected in right),
            len(right),
        )
    return fractions


def _span_counts(case: ReportCase) -> Counts:
    return detection_counts(
        _mention_spans(case.expected_output), _mention_spans(case.output)
    )


#: Agreement is recorded the same way for the annotator alone and for the
#: whole loop, so the two reports subtract.
AGREEMENT_MEASURES: tuple[Measure, ...] = (
    SetAgreement(
        prefix="span",
        counts=_span_counts,
        roles={"f1": Role.PRIMARY, "precision": Role.HEADLINE, "recall": Role.HEADLINE},
    ),
    SetAgreement(
        prefix="cluster",
        counts=_cluster_counts,
        roles={
            "precision": Role.HEADLINE,
            "recall": Role.HEADLINE,
            "f1": Role.HEADLINE,
        },
    ),
    Pooled(
        metric="entity_accuracy", contribution=_entity_agreement, role=Role.HEADLINE
    ),
    CaseMean(score="span_f1", role=Role.HEADLINE),
)

COREFERENCE_HEADLINE = HeadlineDefinition(
    version="coreference-v1", measures=AGREEMENT_MEASURES
)

COREFERENCE_ANNOTATOR_HEADLINE = HeadlineDefinition(
    version="coreference_annotator-v1", measures=AGREEMENT_MEASURES
)


#: Scored the same way for the annotator alone and for the whole loop, so
#: the two reports subtract.
AGREEMENT_EVALUATORS: tuple[Evaluator, ...] = (
    FoundTheSilverMentionSpans(),
    AgreedOnTheCanonicalEntity(),
    MatchedTheSilverClustering(),
    ResolvedWithoutFailing(),
)


COREFERENCE_TASK = register(
    EvaluationTask(
        name="coreference",
        label_quality=LabelQuality.SILVER,
        input_type=CoreferenceInput,
        output_type=CoreferenceExpectation,
        metadata_type=CoreferenceSilverMetadata,
        build=build_task,
        evaluators=(*AGREEMENT_EVALUATORS, RejectedOnlyTheWrongMentionSpans()),
        default_model=default_model(),
        # Both agents, because a loop is not the same loop when either half
        # changed.  The numbered article each also receives is rendered per
        # case, so it belongs to the Silver Set rather than to the prompt.
        prompts=lambda: {
            "annotator": ANNOTATOR_INSTRUCTIONS,
            "critic": CRITIC_INSTRUCTIONS,
        },
        collect=None,
        headline=COREFERENCE_HEADLINE,
    )
)


COREFERENCE_ANNOTATOR_TASK = register(
    EvaluationTask(
        name="coreference_annotator",
        label_quality=LabelQuality.SILVER,
        data_set_name="coreference",
        input_type=CoreferenceInput,
        output_type=CoreferenceExpectation,
        metadata_type=CoreferenceSilverMetadata,
        build=build_annotator_task,
        evaluators=AGREEMENT_EVALUATORS,
        default_model=default_model(),
        prompts=lambda: {"annotator": ANNOTATOR_INSTRUCTIONS},
        collect=None,
        headline=COREFERENCE_ANNOTATOR_HEADLINE,
    )
)
"""The annotator without the Critic, over the same cases as `coreference`.

Run both at one model and subtract: `span_f1` here is the floor, and the
same score there is what the Critic rounds bought. A difference of zero
means the loop is spending its second and third model calls to arrive
where the first one already was.
"""
