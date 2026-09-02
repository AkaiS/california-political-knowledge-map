"""Policy Area Classification as an evaluated task.

Cases come from `evals/gold/policy_area_classification.yaml`, authored
elsewhere and only read here.  It is silver, not gold: labeled by
`claude-opus-5` against
`docs/evaluation/policy-area-classification-annotation.md`, so a run measures
agreement with that annotator and an area both it and the model miss scores as
a pass.

A case is one whole Source Article, as its coreference-resolved text.  That is
what the stage sees in production -- it runs between Coreference Resolution and
chunking -- so it is what a case holds.  The twenty articles are the twenty
Stories of `evals/gold/coreference.yaml`, so every stage is measured over one
population.

Scoring is multi-label agreement over the closed vocabulary: precision, recall
and F1 across an article's areas, so a report tells an article labeled with too
much from one labeled with too little.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from knowledge_map.adapters.policy_areas import (
    PolicyAreaClassificationError,
    PydanticAIPolicyAreaAdapter,
    get_classification_agent,
)
from knowledge_map.schemas import DeploymentKind, ModelDeployment, PolicyAreaName
from knowledge_map.utils.models import (
    DEFAULT_LOCAL_CHAT_MODEL,
    resolve_local_chat_model,
)

from .registry import EvaluationTask, register

FALLBACK_MODEL = DEFAULT_LOCAL_CHAT_MODEL


def default_model() -> str:
    """The model Policy Area Classification runs in production, per `.env`.

    Supplies the default a run records when `--model` is not given.  Called
    at import, so it loads `.env` itself.
    """

    return resolve_local_chat_model(FALLBACK_MODEL)


class ClassificationInput(BaseModel):
    """One Source Article as the classification agent sees it.

    The agent is shown `resolved_text` alone; `url` and `title` are carried so
    a report names something a person can open.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    resolved_text: str


class ClassificationExpectation(BaseModel):
    """The Policy Areas silver says one Source Article discusses.

    An empty list is an answer: the vocabulary does not cover this article.

    Typed by `PolicyAreaName` rather than by `str` so that a silver label
    outside the closed vocabulary -- a stale name, or an id where the name
    belongs -- fails when the Gold Set is read rather than scoring a silent
    zero against every model on every run.
    """

    model_config = ConfigDict(extra="forbid")

    policy_areas: list[PolicyAreaName] = Field(default_factory=list)


class ClassificationOutput(BaseModel):
    """What one classification attempt produced, including its own failure.

    A failed classification is scored as a zero rather than raised, so it stays
    in the population.  That is why `policy_areas` is `str` here where the
    expectation is `PolicyAreaName`: this side holds what a model produced, and
    an off-vocabulary answer is a result to score, not a case to crash.
    """

    model_config = ConfigDict(extra="forbid")

    policy_areas: list[str] = Field(default_factory=list)
    failure_type: str | None = None


class ClassificationSilverMetadata(BaseModel):
    """Source and model provenance for one silver-labeled Source Article.

    ``coreference_gold_set`` names the file the article's resolved text came
    from, because re-resolving these articles from a later revision of that
    file would silently change what every case is asking about.
    """

    model_config = ConfigDict(extra="forbid")

    source_table: Literal["stories"]
    story_id: int
    label_quality: Literal["silver"]
    annotator_model: str
    annotation_guideline: str
    coreference_gold_set: str


def _as_deployment(model: str | ModelDeployment) -> ModelDeployment:
    """Turn a legacy model argument into an explicit local deployment."""

    if isinstance(model, ModelDeployment):
        return model
    return ModelDeployment(kind=DeploymentKind.LOCAL, model=model)


def build_task(model: str | ModelDeployment, gold_set: Any) -> Any:
    """Return the callable one case is run through, bound to a deployment.

    `gold_set` is in the signature for the registry's uniform call and goes
    unused; nothing here few-shots.  The stage under test is the adapter's
    `classify`, so a run measures the vocabulary the stage owns rather than a
    prompt this file would otherwise restate.
    """

    del gold_set

    deployment = _as_deployment(model)
    adapter = PydanticAIPolicyAreaAdapter(
        agent=get_classification_agent(deployment), deployment=deployment
    )

    def classify(case_input: ClassificationInput) -> ClassificationOutput:
        try:
            areas = adapter.classify(case_input.resolved_text)
        except PolicyAreaClassificationError as error:
            return ClassificationOutput(failure_type=error.failure_type)
        return ClassificationOutput(policy_areas=areas)

    return classify


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0.0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


class AgreedOnThePolicyAreas(Evaluator):
    """The same Policy Areas were chosen, by canonical name.

    Multi-label agreement over the closed vocabulary, as a set: the stage
    writes one topic edge per area, so an area named twice is one area and a
    reordered answer is the same answer.

    Read precision and recall apart.  An area silver did not give is a hub two
    unrelated articles now meet at; an area silver gave and the model did not
    is an article missing from the hub it belongs to.

    An article silver left empty that the model also left empty is a pass on
    all three scores, not an unscoreable case -- agreeing that the vocabulary
    does not cover an article is the correct answer, and the report says so.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float]:
        expected = set(ctx.expected_output.policy_areas)
        found = set(ctx.output.policy_areas)
        if not expected and not found:
            return {
                "policy_area_precision": 1.0,
                "policy_area_recall": 1.0,
                "policy_area_f1": 1.0,
            }
        matched = len(expected & found)
        precision = matched / len(found) if found else 0.0
        recall = matched / len(expected) if expected else 0.0
        return {
            "policy_area_precision": precision,
            "policy_area_recall": recall,
            "policy_area_f1": _f1(precision, recall),
        }


class ClassifiedWithoutFailing(Evaluator):
    """The run produced a classification instead of raising.

    Read alongside the agreement scores to tell a run that failed outright
    from one that answered badly; both score zero there.
    """

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output.failure_type is None


POLICY_AREA_CLASSIFICATION_TASK = register(
    EvaluationTask(
        name="policy_area_classification",
        input_type=ClassificationInput,
        output_type=ClassificationExpectation,
        metadata_type=ClassificationSilverMetadata,
        build=build_task,
        evaluators=(
            AgreedOnThePolicyAreas(),
            ClassifiedWithoutFailing(),
        ),
        default_model=default_model(),
        collect=None,
    )
)
