"""Coreference Resolution as an evaluated task.

The Gold Set for this task is `evals/gold/coreference.yaml`, and it is
silver rather than gold: every Mention Span in it was annotated and then
criticized by `gpt-5.6-sol`, not by the author. A run therefore measures
agreement with that model. A case both models get wrong scores as a pass,
which is the standing limitation of the file and not of this module.

Two tasks are registered against that one file. `coreference` runs the
whole loop; `coreference_annotator` runs the annotator alone and skips the
Critic. The difference between their reports is what the Critic rounds are
worth, which no single report can show: a mediocre pipeline score is the
same number whether the annotator is weak or the Critic is deleting its
correct work, and those point at opposite prompts.

There is no `collect` here. The Relevance Filter could read its cases out
of `scraped_html_cache` because the author had already labeled those rows
by hand; nothing in this project's database holds a Mention Span the
author labeled, so the file is authored elsewhere and only read here.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from knowledge_map.adapters.coreference import (
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
)
from knowledge_map.utils.models import get_chat_model

from .registry import EvaluationTask, register

FALLBACK_MODEL = "8k-gemma-e4b-extraction"


def default_model() -> str:
    """The model Coreference Resolution runs in production, per `.env`.

    Read once, here, to supply the default a run then records. The task
    itself is built with `allow_env_override=False` so that an explicit
    `--model` is the model actually sent; resolving it a second time at
    call time would let `OLLAMA_MODEL` replace it silently.

    `load_dotenv` is called because this runs at import, before anything
    else has read the file: without it every variable below is unset and
    the fallback wins, so a run with no `--model` would record a model
    name that appears nowhere in this project's configuration.
    """

    load_dotenv()
    return (
        os.environ.get("OLLAMA_MODEL_COREFERENCE")
        or os.environ.get("OLLAMA_MODEL")
        or FALLBACK_MODEL
    )


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

    A failed resolution is an outcome to be scored rather than an error to
    abort on: a model that gives up on six of twenty Stories is telling
    you something, and a raised exception would remove those six from the
    population instead of counting them as zeros.
    """

    model_config = ConfigDict(extra="forbid")

    mention_spans: list[MentionSpan] = Field(default_factory=list)
    outcomes: list[MentionSpanOutcome] = Field(default_factory=list)
    """Every Mention Span the run ruled on, with the stage that ruled.

    Carried so the Coreference Critic can be scored without a Gold Set of
    verdicts: each outcome names the span it judged, and the silver file
    says what that span should have been.
    """
    failure_type: str | None = None
    retry_count: int = 0
    discarded_proportion: float = 0.0


class CoreferenceSilverMetadata(BaseModel):
    """Source and model provenance for one silver-labeled Story.

    There is no critic provenance here because the annotation is a single
    pass against a written guideline rather than an annotator/critic loop.
    ``annotation_guideline`` names that guideline, which is the only thing
    that makes one case's judgment calls comparable to another's.
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

    The outcomes travel even here. A run that failed because the Critic
    rejected everything is precisely the run whose Critic decisions are
    worth reading, and dropping them would hide the evidence in the case
    that produced the most of it.
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


def build_task(model: str, gold_set: Any) -> Any:
    """Return the callable one case is run through, bound to ``model``.

    `gold_set` is unused: nothing in this task few-shots, so there is no
    reason to read the `training` split. It stays in the signature because
    the registry calls every task the same way.

    The callable is synchronous because `resolve_coreferences_run` is, all
    the way down to `Agent.run_sync`. Pydantic Evals runs a synchronous
    task in a worker thread, so `--max-concurrency` still parallelizes and
    `run_sync` still finds no event loop of its own to collide with.
    """

    del gold_set

    chat_model = get_chat_model(model, allow_env_override=False)
    annotator_agent = get_annotator_agent()
    critic_agent = get_critic_agent()

    def resolve(case_input: CoreferenceInput) -> CoreferenceOutput:
        # `override` rather than assigning `.model`, so the agents keep the
        # instructions, output validator and retry budget they run with in
        # production and only the weights behind them change.
        try:
            with (
                annotator_agent.override(model=chat_model),
                critic_agent.override(model=chat_model),
            ):
                run = resolve_coreferences_run(
                    case_input.content,
                    annotator_agent=annotator_agent,
                    critic_agent=critic_agent,
                    max_critic_rounds=settings.coreference.max_critic_rounds,
                )
        except CoreferenceResolutionError as error:
            return _output_from_failure(error)
        return _output_from_run(run)

    return resolve


def build_annotator_task(model: str, gold_set: Any) -> Any:
    """Return the callable for one annotator-only case, bound to ``model``.

    No Critic agent is built at all, rather than built and left unused: the
    baseline this task measures is the annotator answering once, and a
    Critic in scope is a Critic something can accidentally call.
    """

    del gold_set

    chat_model = get_chat_model(model, allow_env_override=False)
    annotator_agent = get_annotator_agent()

    def annotate(case_input: CoreferenceInput) -> CoreferenceOutput:
        try:
            with annotator_agent.override(model=chat_model):
                run = annotate_coreferences_run(
                    case_input.content,
                    annotator_agent=annotator_agent,
                )
        except CoreferenceResolutionError as error:
            return _output_from_failure(error)
        return _output_from_run(run)

    return annotate


def normalize_entity_name(name: str) -> str:
    """Fold case and collapse whitespace, and change nothing else.

    "Steve  Hilton" and "steve hilton" are the same answer written twice.
    "Hilton" is not: shortening a canonical name is a real difference in
    what the graph would key on, so it is left as a mismatch here and
    caught instead by the clustering evaluator, which does not read names.
    """

    return " ".join(name.split()).casefold()


def entity_by_identity(
    mention_spans: Sequence[MentionSpan],
) -> dict[MentionSpanIdentity, str]:
    """Index one entity name per text location, last one winning.

    `MentionSpanIdentity` deliberately excludes the canonical entity name,
    so two Mention Spans naming one location with different entities share
    a key. Last-wins is what `ResolutionState` does with the same
    collision, and scoring has to agree with the run it is scoring.
    """

    return {
        MentionSpanIdentity.of(span): normalize_entity_name(span.canonical_entity_name)
        for span in mention_spans
    }


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0.0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


class FoundTheSilverMentionSpans(Evaluator):
    """The same *mentions* were found, whatever they were said to refer to.

    Detection scored on its own, keyed by text location alone. Recall is
    the number to watch: a mention the annotator never proposed cannot be
    recovered by the Critic, so it is gone from the graph, while a spurious
    one costs only a wrong substitution.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float]:
        expected = set(entity_by_identity(ctx.expected_output.mention_spans))
        found = set(entity_by_identity(ctx.output.mention_spans))
        matched = len(expected & found)

        precision = matched / len(found) if found else 0.0
        recall = matched / len(expected) if expected else 0.0
        return {
            "span_precision": precision,
            "span_recall": recall,
            "span_f1": _f1(precision, recall),
        }


class AgreedOnTheCanonicalEntity(Evaluator):
    """Of the mentions both found, how many carry the same entity name.

    Conditional on detection, so it answers "when it saw the mention, did
    it name the right entity" rather than mixing that with whether it saw
    the mention at all. Returns `None` when the two sets share no location,
    because 0 would read as total disagreement about entities when in fact
    there was nothing to disagree about.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float] | None:
        expected = entity_by_identity(ctx.expected_output.mention_spans)
        found = entity_by_identity(ctx.output.mention_spans)
        shared = expected.keys() & found.keys()
        if not shared:
            return None
        agreed = sum(expected[key] == found[key] for key in shared)
        return {"entity_accuracy": agreed / len(shared)}


class MatchedTheSilverClustering(Evaluator):
    """The same *partition* of mentions, whatever the clusters were called.

    B-cubed over the locations both sides found. Coreference is a
    partition problem, and a model that groups every Hilton mention
    together but calls the group "Hilton" has made a naming choice, not a
    coreference error; `AgreedOnTheCanonicalEntity` scores that as a miss
    and this does not. What this does catch is the error that matters:
    two people merged into one cluster, or one person split across two.

    Restricting to the shared locations keeps detection errors out of the
    number -- they are already counted by `FoundTheSilverMentionSpans`, and
    a mention only one side found belongs to no cluster on the other.
    Returns `None` on an empty intersection, for the reason above.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float] | None:
        expected = entity_by_identity(ctx.expected_output.mention_spans)
        found = entity_by_identity(ctx.output.mention_spans)
        shared = sorted(
            expected.keys() & found.keys(),
            key=lambda key: (key.sentence_label, key.mention_text, key.occurrence),
        )
        if not shared:
            return None

        expected_clusters = _clusters(shared, expected)
        found_clusters = _clusters(shared, found)

        precision = 0.0
        recall = 0.0
        for key in shared:
            gold = expected_clusters[expected[key]]
            predicted = found_clusters[found[key]]
            overlap = len(gold & predicted)
            precision += overlap / len(predicted)
            recall += overlap / len(gold)
        precision /= len(shared)
        recall /= len(shared)

        return {
            "cluster_precision": precision,
            "cluster_recall": recall,
            "cluster_f1": _f1(precision, recall),
        }


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

    Scored because a model can fail this task in a way the other three
    cannot see: every span rejected, or output that never validates. Those
    runs score zero everywhere else, and this is what distinguishes zero
    from a model that answered and answered badly.
    """

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output.failure_type is None


class RejectedOnlyTheWrongMentionSpans(Evaluator):
    """What the Coreference Critic's rejections were actually worth.

    Read out of the run's own audit trail, because a Gold Set of verdicts
    does not exist and would have to be authored: every outcome carries the
    Mention Span it ruled on, and the silver file says what that span should
    have been. A Critic decision is judgeable whenever silver annotated the
    same location.

    Spans silver never annotated are skipped rather than counted wrong.
    Silver is one model's answer and its silence about a location is not
    evidence that a span there is mistaken; counting it as one would turn
    every mention silver simply missed into a Critic error.

    Outcomes are last-wins, so a span rejected in one round and corrected in
    the next appears here as the acceptance the run ended on. These are the
    Critic's net decisions, which is the right unit: a rejection the
    annotator repaired cost a round, not an answer.

    Returns `None` when nothing was judgeable -- including every
    `coreference_annotator` run, where no outcome has a `critic` stage at
    all, so the same evaluator can sit on both tasks without reporting a
    Critic that never ran.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float] | None:
        silver = entity_by_identity(ctx.expected_output.mention_spans)

        # (the span was correct, the Critic rejected it)
        judged: list[tuple[bool, bool]] = []
        for outcome in ctx.output.outcomes:
            if outcome.stage != "critic":
                continue
            expected_entity = silver.get(MentionSpanIdentity.of(outcome.mention_span))
            if expected_entity is None:
                continue
            judged.append(
                (
                    expected_entity
                    == normalize_entity_name(
                        outcome.mention_span.canonical_entity_name
                    ),
                    outcome.outcome == "rejected",
                )
            )

        if not judged:
            return None

        rejected = [correct for correct, was_rejected in judged if was_rejected]
        wrong = [was_rejected for correct, was_rejected in judged if not correct]
        right = [was_rejected for correct, was_rejected in judged if correct]

        scores: dict[str, float] = {}
        if rejected:
            # Of what it threw away, how much deserved it.
            scores["critic_rejection_precision"] = sum(
                not correct for correct in rejected
            ) / len(rejected)
        if wrong:
            # Of the mistakes it was shown, how many it caught.
            scores["critic_rejection_recall"] = sum(wrong) / len(wrong)
        if right:
            # Of the correct spans it was shown, how many it left alone.
            # Phrased so that higher is better, like every other score in
            # this report; it is the complement of a false-rejection rate,
            # and a column where low means good invites misreading.
            scores["critic_kept_correct_spans"] = sum(
                not was_rejected for was_rejected in right
            ) / len(right)
        return scores or None


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
        input_type=CoreferenceInput,
        output_type=CoreferenceExpectation,
        metadata_type=CoreferenceSilverMetadata,
        build=build_task,
        evaluators=(*AGREEMENT_EVALUATORS, RejectedOnlyTheWrongMentionSpans()),
        default_model=default_model(),
        collect=None,
    )
)


COREFERENCE_ANNOTATOR_TASK = register(
    EvaluationTask(
        name="coreference_annotator",
        gold_set_name="coreference",
        input_type=CoreferenceInput,
        output_type=CoreferenceExpectation,
        metadata_type=CoreferenceSilverMetadata,
        build=build_annotator_task,
        evaluators=AGREEMENT_EVALUATORS,
        default_model=default_model(),
        collect=None,
    )
)
"""The annotator without the Critic, over the same cases as `coreference`.

Run both at one model and subtract: `span_f1` here is the floor, and the
same score there is what the Critic rounds bought. A difference of zero
means the loop is spending its second and third model calls to arrive
where the first one already was.
"""
