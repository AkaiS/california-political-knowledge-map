"""Topic Assignment as an evaluated task.

Cases come from `evals/silver/topic_assignment.yaml`, authored elsewhere and only
read here.  It is silver, not gold: labeled by `claude-opus-5` against
`docs/evaluation/topic-assignment-annotation.md`, so a run measures agreement
with that annotator and a pair both it and the model miss scores as a pass.

A case is one whole Source Article together with the two things the stage is
given beside it: the Policy Areas classification found, and every Bill and Prop
the article's extractions produced.  That is the stage's whole input in
production, so it is what a case holds.  The twenty articles are the twenty
Stories of `evals/silver/coreference.yaml`, so every stage is measured over one
population.

Scoring is on measure-to-area **pairs**, with the measure named by extraction's
surface string.  An article whose areas are right but whose bills are
mismatched cannot score as a pass, because a pair is only matched when both of
its endpoints are.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from knowledge_map.adapters.policy_areas import (
    ASSIGNMENT_INSTRUCTIONS,
    PydanticAIPolicyAreaAdapter,
    TopicAssignmentError,
    get_assignment_agent,
)
from knowledge_map.core.topic_assignment import MEASURE_LABELS
from knowledge_map.schemas import (
    ModelDeployment,
    Node,
    PolicyAreaName,
    SourceArticle,
    TopicAssignment,
)

from ..data_set import LabelQuality
from ..deployment import as_deployment, default_model
from ..scoring import detection_scores
from .extraction import normalize_name
from .registry import EvaluationTask, register

#: The measure labels an `ABOUT_TOPIC` edge may start from, as the silver side
#: is allowed to write them.  Read from the ontology through the stage that
#: collects the measures, so a label the graph could never hold fails when the
#: Silver Set is read rather than scoring a silent zero on every run.
MeasureLabel = Literal[tuple(sorted(MEASURE_LABELS))]  # type: ignore[valid-type]


class AssignmentMeasure(BaseModel):
    """One Bill or Prop the article's extractions produced.

    `name` is the surface string extraction reported, which is how the write
    path resolves the measure's node and therefore how an assignment has to
    name it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    label: MeasureLabel


class AssignmentInput(BaseModel):
    """One Source Article as the assignment stage sees it.

    All three fields are the stage's input, not context: it is given the
    article, the areas classification chose, and the measures extraction
    found, and it is the only stage that sees all three at once.

    `resolved_text` is the article after the accepted silver Mention Spans
    have been substituted, the same text every other article-level case in
    this population holds.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    resolved_text: str
    policy_areas: list[PolicyAreaName] = Field(default_factory=list)
    measures: list[AssignmentMeasure] = Field(default_factory=list)


class SilverTopicAssignment(BaseModel):
    """One measure-to-area pair silver says the article supports.

    Both halves are typed rather than left as `str`.  `policy_area` is a
    `PolicyAreaName` because an area outside the closed vocabulary is one the
    classified set could never contain and the write path could never key;
    `measure_label` is a `MeasureLabel` because an `ABOUT_TOPIC` edge starts
    nowhere else.  Either mistake fails when the Silver Set is read rather than
    scoring a silent zero against every model on every run.

    The one half no type can guard is the measure's surface string, which is
    free text by construction.  Its guard is the Silver Set's loading test:
    every measure a case names is one the extraction Silver Set or the article
    itself contains.
    """

    model_config = ConfigDict(extra="forbid")

    measure_name: str = Field(..., min_length=1)
    measure_label: MeasureLabel
    policy_area: PolicyAreaName


class AssignmentExpectation(BaseModel):
    """The measure-to-area pairs silver says one Source Article supports.

    An empty list is an answer: this article connects none of its measures to
    any of its areas, or it names no measures at all.
    """

    model_config = ConfigDict(extra="forbid")

    assignments: list[SilverTopicAssignment] = Field(default_factory=list)


class AssignmentOutput(BaseModel):
    """What one assignment attempt produced, including its own failure.

    A failed assignment is scored as a zero rather than raised, so it stays in
    the population.  That is why the assignments here are the stage's own
    `TopicAssignment`, whose area is `str`: this side holds what a model
    produced, and an off-vocabulary answer is a result to score, not a case to
    crash.
    """

    model_config = ConfigDict(extra="forbid")

    assignments: list[TopicAssignment] = Field(default_factory=list)
    failure_type: str | None = None


class AssignmentSilverMetadata(BaseModel):
    """Source and model provenance for one silver-labeled Source Article.

    `coreference_silver_set` and `extraction_silver_set` name the files a case's
    text and measures were taken from, because re-deriving either from a later
    revision would silently change what the case is asking about.
    """

    model_config = ConfigDict(extra="forbid")

    source_table: Literal["stories"]
    story_id: int
    label_quality: Literal["silver"]
    annotator_model: str
    annotation_guideline: str
    coreference_silver_set: str
    extraction_silver_set: str


def build_task(model: str | ModelDeployment, data_set: Any) -> Any:
    """Return the callable one case is run through, bound to a deployment.

    `data_set` is in the signature for the registry's uniform call and goes
    unused; nothing here few-shots.  The stage under test is the adapter's
    `assign`, so a run measures the judgement the stage owns rather than a
    prompt this file would otherwise restate.

    The two drops the pipeline applies after the stage are deliberately not
    applied here.  They exist to keep a hallucinated endpoint from reaching
    the write path; applying them to a score would hide the hallucination they
    were built to contain, so an assignment naming a measure or an area it was
    not given costs precision in the report instead.
    """

    del data_set

    deployment = as_deployment(model)
    adapter = PydanticAIPolicyAreaAdapter(
        assignment_agent=get_assignment_agent(deployment), deployment=deployment
    )

    def assign(case_input: AssignmentInput) -> AssignmentOutput:
        # With no areas or no measures the pipeline never reaches the stage,
        # so neither does a case: there is nothing to decide between.
        if not case_input.policy_areas or not case_input.measures:
            return AssignmentOutput()

        article = SourceArticle(
            url=case_input.url,
            title=case_input.title,
            content=case_input.resolved_text,
        )
        measures = [
            Node(name=measure.name, label=measure.label)
            for measure in case_input.measures
        ]
        try:
            assignments = adapter.assign(
                article, list(case_input.policy_areas), measures
            )
        except TopicAssignmentError as error:
            return AssignmentOutput(failure_type=error.failure_type)
        return AssignmentOutput(assignments=assignments)

    return assign


#: One pair, as both sides are compared: the measure's surface string folded
#: for case and spacing, its label, and the area's canonical name.
PairIdentity = tuple[str, str, str]


def _identity(assignment: TopicAssignment | SilverTopicAssignment) -> PairIdentity:
    """A pair's identity, folded exactly as far as the write path folds it.

    `normalize_name` is the extraction task's rule, applied here for the same
    reason: the measure is named by extraction's surface string, and case and
    spacing are the only difference that is not a different measure.  A
    shortened or expanded designation stays a mismatch.
    """

    return (
        normalize_name(assignment.measure_name),
        assignment.measure_label,
        assignment.policy_area,
    )


class AgreedOnTheTopicAssignments(Evaluator):
    """The same measures were connected to the same Policy Areas.

    Scored on pairs rather than on the areas and the measures apart, because
    the pair is what the stage writes: an article whose areas are right and
    whose bills are mismatched has written the wrong edges and the report has
    to say so.

    Read precision and recall apart.  A pair silver did not give is a topic
    edge asserting something the article never said; a pair silver gave and
    the model did not is a measure absent from the hub it belongs to.

    An article silver supports no pairs for, and the model returned none for,
    is a pass on all three scores rather than an unscoreable case -- assigning
    nothing is the correct answer for an article whose measures it does not
    connect to its areas, and the report says so.
    """

    def evaluate(self, ctx: EvaluatorContext) -> Mapping[str, float]:
        expected = {_identity(pair) for pair in ctx.expected_output.assignments}
        found = {_identity(pair) for pair in ctx.output.assignments}
        if not expected and not found:
            return {
                "assignment_precision": 1.0,
                "assignment_recall": 1.0,
                "assignment_f1": 1.0,
            }
        return detection_scores(expected, found, "assignment")


class AssignedWithoutFailing(Evaluator):
    """The run produced assignments instead of raising.

    Read alongside the agreement scores to tell a run that failed outright
    from one that answered badly; both score zero there.
    """

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output.failure_type is None


TOPIC_ASSIGNMENT_TASK = register(
    EvaluationTask(
        name="topic_assignment",
        label_quality=LabelQuality.SILVER,
        input_type=AssignmentInput,
        output_type=AssignmentExpectation,
        metadata_type=AssignmentSilverMetadata,
        build=build_task,
        evaluators=(
            AgreedOnTheTopicAssignments(),
            AssignedWithoutFailing(),
        ),
        default_model=default_model(),
        prompts=lambda: {"assignment": ASSIGNMENT_INSTRUCTIONS},
        collect=None,
    )
)
