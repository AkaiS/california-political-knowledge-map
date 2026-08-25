"""Coreference Resolution as an evaluated task.

The Gold Set for this task is `evals/gold/coreference.yaml`, and it is
silver rather than gold: every Mention Span in it was annotated and then
criticized by `gpt-5.6-sol`, not by the author. A run therefore measures
agreement with that model. A case both models get wrong scores as a pass,
which is the standing limitation of the file and not of this module.

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
    get_annotator_agent,
    get_critic_agent,
    resolve_coreferences_run,
)
from knowledge_map.config import settings
from knowledge_map.schemas import MentionSpan
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
    failure_type: str | None = None
    retry_count: int = 0
    discarded_proportion: float = 0.0


class CoreferenceSilverMetadata(BaseModel):
    """Source and model provenance for one silver-labeled Story."""

    model_config = ConfigDict(extra="forbid")

    source_table: Literal["stories"]
    story_id: int
    label_quality: Literal["silver"]
    annotator_model: str
    annotator_reasoning_effort: str
    critic_model: str
    critic_reasoning_effort: str


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
            failed = error.resolution_run
            return CoreferenceOutput(
                failure_type=error.failure_type,
                retry_count=0 if failed is None else failed.retry_count,
                discarded_proportion=(
                    0.0 if failed is None else failed.discarded_proportion
                ),
            )
        return CoreferenceOutput(
            mention_spans=run.surviving_spans,
            failure_type=run.failure_type,
            retry_count=run.retry_count,
            discarded_proportion=run.discarded_proportion,
        )

    return resolve


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


COREFERENCE_TASK = register(
    EvaluationTask(
        name="coreference",
        input_type=CoreferenceInput,
        output_type=CoreferenceExpectation,
        metadata_type=CoreferenceSilverMetadata,
        build=build_task,
        evaluators=(
            FoundTheSilverMentionSpans(),
            AgreedOnTheCanonicalEntity(),
            MatchedTheSilverClustering(),
            ResolvedWithoutFailing(),
        ),
        default_model=default_model(),
        collect=None,
    )
)
