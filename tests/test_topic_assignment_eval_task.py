"""The Topic Assignment evaluators score what they claim to score."""

import pytest
from pydantic_evals.evaluators import EvaluatorContext

from knowledge_map.adapters.policy_areas import TopicAssignmentError
from knowledge_map.evaluation.tasks import task_named, topic_assignment
from knowledge_map.evaluation.tasks.topic_assignment import (
    AgreedOnTheTopicAssignments,
    AssignedWithoutFailing,
    AssignmentExpectation,
    AssignmentInput,
    AssignmentMeasure,
    AssignmentOutput,
    SilverTopicAssignment,
)
from knowledge_map.schemas import TopicAssignment

HEALTH = "Health"
HOUSING = "Housing & Community Development"
LABOR = "Labor & Employment"

SB_9 = ("SB 9", "Bill")
PROP_38 = ("Proposition 38", "Prop")


def _pair(measure: tuple[str, str], area: str) -> SilverTopicAssignment:
    return SilverTopicAssignment(
        measure_name=measure[0], measure_label=measure[1], policy_area=area
    )


def _returned(measure: tuple[str, str], area: str) -> TopicAssignment:
    return TopicAssignment(
        measure_name=measure[0], measure_label=measure[1], policy_area=area
    )


def _context(expected: AssignmentExpectation, output: AssignmentOutput):
    """One EvaluatorContext holding a silver answer and a model answer."""

    return EvaluatorContext(
        name="case",
        inputs=AssignmentInput(
            url="https://example.test/a",
            title="A",
            resolved_text="a",
            policy_areas=[HEALTH],
            measures=[AssignmentMeasure(name="SB 9", label="Bill")],
        ),
        metadata=None,
        expected_output=expected,
        output=output,
        duration=0.0,
        _span_tree=None,
        attributes={},
        metrics={},
    )


def _scored(evaluator, *, expected=(), returned=(), **output_kwargs):
    return evaluator.evaluate(
        _context(
            AssignmentExpectation(assignments=list(expected)),
            AssignmentOutput(assignments=list(returned), **output_kwargs),
        )
    )


def test_naming_exactly_the_silver_pairs_scores_one_on_every_metric() -> None:
    scores = _scored(
        AgreedOnTheTopicAssignments(),
        expected=(_pair(SB_9, HOUSING), _pair(PROP_38, HEALTH)),
        returned=(_returned(PROP_38, HEALTH), _returned(SB_9, HOUSING)),
    )

    assert scores == {
        "assignment_precision": 1.0,
        "assignment_recall": 1.0,
        "assignment_f1": 1.0,
    }


def test_the_right_areas_on_the_wrong_measure_cannot_score_as_a_pass() -> None:
    """The whole point of scoring pairs: areas alone are not the answer."""

    scores = _scored(
        AgreedOnTheTopicAssignments(),
        expected=(_pair(SB_9, HOUSING),),
        returned=(_returned(PROP_38, HOUSING),),
    )

    assert scores == {
        "assignment_precision": 0.0,
        "assignment_recall": 0.0,
        "assignment_f1": 0.0,
    }


def test_the_right_measure_under_the_wrong_area_scores_zero() -> None:
    scores = _scored(
        AgreedOnTheTopicAssignments(),
        expected=(_pair(SB_9, HOUSING),),
        returned=(_returned(SB_9, LABOR),),
    )

    assert scores["assignment_f1"] == 0.0


def test_a_missed_pair_costs_recall_and_leaves_precision_whole() -> None:
    scores = _scored(
        AgreedOnTheTopicAssignments(),
        expected=(_pair(SB_9, HOUSING), _pair(SB_9, LABOR)),
        returned=(_returned(SB_9, HOUSING),),
    )

    assert scores["assignment_precision"] == 1.0
    assert scores["assignment_recall"] == 0.5
    assert scores["assignment_f1"] == pytest.approx(2 / 3)


def test_an_extra_pair_costs_precision_and_leaves_recall_whole() -> None:
    scores = _scored(
        AgreedOnTheTopicAssignments(),
        expected=(_pair(SB_9, HOUSING),),
        returned=(_returned(SB_9, HOUSING), _returned(SB_9, LABOR)),
    )

    assert scores["assignment_precision"] == 0.5
    assert scores["assignment_recall"] == 1.0


def test_an_article_supporting_no_pairs_answered_with_none_is_a_pass() -> None:
    """Not an unscoreable case: making no assignment is the right answer."""

    scores = _scored(AgreedOnTheTopicAssignments(), expected=(), returned=())

    assert scores == {
        "assignment_precision": 1.0,
        "assignment_recall": 1.0,
        "assignment_f1": 1.0,
    }


def test_an_article_supporting_no_pairs_answered_with_some_scores_zero() -> None:
    scores = _scored(
        AgreedOnTheTopicAssignments(), expected=(), returned=(_returned(SB_9, HOUSING),)
    )

    assert scores == {
        "assignment_precision": 0.0,
        "assignment_recall": 0.0,
        "assignment_f1": 0.0,
    }


def test_an_article_supporting_pairs_answered_with_none_scores_zero() -> None:
    scores = _scored(
        AgreedOnTheTopicAssignments(), expected=(_pair(SB_9, HOUSING),), returned=()
    )

    assert scores["assignment_recall"] == 0.0


def test_a_pair_returned_twice_is_one_pair() -> None:
    """The stage writes one topic edge per pair, so a repeat cannot cost precision."""

    scores = _scored(
        AgreedOnTheTopicAssignments(),
        expected=(_pair(SB_9, HOUSING),),
        returned=(_returned(SB_9, HOUSING), _returned(SB_9, HOUSING)),
    )

    assert scores["assignment_precision"] == 1.0


def test_the_measure_surface_string_matches_on_case_and_spacing_alone() -> None:
    """`sb  9` is the same surface string; `Senate Bill 9` is a different one.

    Extraction's surface string is the name, and the write path keys on it.
    Folding case and whitespace is the only latitude a report gives a model.
    """

    matched = _scored(
        AgreedOnTheTopicAssignments(),
        expected=(_pair(SB_9, HOUSING),),
        returned=(_returned(("sb  9", "Bill"), HOUSING),),
    )
    expanded = _scored(
        AgreedOnTheTopicAssignments(),
        expected=(_pair(SB_9, HOUSING),),
        returned=(_returned(("Senate Bill 9", "Bill"), HOUSING),),
    )

    assert matched["assignment_f1"] == 1.0
    assert expanded["assignment_f1"] == 0.0


def test_the_same_designation_under_a_different_label_is_a_different_measure() -> None:
    scores = _scored(
        AgreedOnTheTopicAssignments(),
        expected=(_pair(("Proposition 38", "Prop"), HEALTH),),
        returned=(_returned(("Proposition 38", "Bill"), HEALTH),),
    )

    assert scores["assignment_f1"] == 0.0


def test_a_failed_assignment_is_scored_rather_than_raised() -> None:
    assert (
        _scored(AssignedWithoutFailing(), expected=(_pair(SB_9, HOUSING),), returned=())
        is True
    )
    assert (
        _scored(
            AssignedWithoutFailing(),
            expected=(_pair(SB_9, HOUSING),),
            returned=(),
            failure_type="topic_assignment_failure",
        )
        is False
    )


def test_a_failed_assignment_still_scores_the_pairs_it_did_not_return() -> None:
    """A failure stays in the population as a zero instead of leaving it."""

    scores = _scored(
        AgreedOnTheTopicAssignments(),
        expected=(_pair(SB_9, HOUSING),),
        returned=(),
        failure_type="topic_assignment_failure",
    )

    assert scores["assignment_recall"] == 0.0


class _RecordingAdapter:
    """Stands in for the Pydantic AI adapter, and records what it was asked."""

    def __init__(self, *args, raises: Exception | None = None, **kwargs) -> None:
        self.calls: list[tuple] = []
        self.raises = raises

    def assign(self, article, policy_areas, measures):
        self.calls.append((article, policy_areas, measures))
        if self.raises is not None:
            raise self.raises
        return [_returned(SB_9, HOUSING)]


def _built(monkeypatch, adapter):
    """The registered task's callable, bound to a stand-in adapter."""

    monkeypatch.setattr(
        topic_assignment, "PydanticAIPolicyAreaAdapter", lambda *a, **k: adapter
    )
    monkeypatch.setattr(topic_assignment, "get_assignment_agent", lambda *a, **k: None)
    return task_named("topic_assignment").build("a-model", None)


def _case_input(*, policy_areas=(HOUSING,), measures=(("SB 9", "Bill"),)):
    return AssignmentInput(
        url="https://example.test/a",
        title="A",
        resolved_text="the article",
        policy_areas=list(policy_areas),
        measures=[
            AssignmentMeasure(name=name, label=label) for name, label in measures
        ],
    )


def test_the_stage_under_test_is_the_assignment_adapter(monkeypatch) -> None:
    """A run measures `assign` over the stage's own three inputs."""

    adapter = _RecordingAdapter()

    output = _built(monkeypatch, adapter)(_case_input())

    (article, policy_areas, measures) = adapter.calls[0]
    assert article.url == "https://example.test/a"
    assert article.content == "the article"
    assert policy_areas == [HOUSING]
    assert [(node.name, node.label) for node in measures] == [("SB 9", "Bill")]
    assert output.assignments == [_returned(SB_9, HOUSING)]
    assert output.failure_type is None


def test_an_article_with_no_measures_or_no_areas_never_reaches_the_stage(
    monkeypatch,
) -> None:
    """The pipeline skips the stage there, so a case cannot ask it the question."""

    adapter = _RecordingAdapter()
    assign = _built(monkeypatch, adapter)

    no_measures = assign(_case_input(measures=()))
    no_areas = assign(_case_input(policy_areas=()))

    assert adapter.calls == []
    assert no_measures.assignments == []
    assert no_areas.assignments == []
    assert no_measures.failure_type is None


def test_a_stage_failure_is_recorded_rather_than_raised(monkeypatch) -> None:
    adapter = _RecordingAdapter(
        raises=TopicAssignmentError(original_text="the article")
    )

    output = _built(monkeypatch, adapter)(_case_input())

    assert output.failure_type == "topic_assignment_failure"
    assert output.assignments == []


def test_the_task_is_registered_with_its_own_types() -> None:
    task = task_named("topic_assignment")

    assert task.input_type is AssignmentInput
    assert task.output_type is AssignmentExpectation
    assert task.data_set_stem == "topic_assignment"
