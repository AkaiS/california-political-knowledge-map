"""The Policy Area Classification evaluators score what they claim to score."""

import pytest
from pydantic_evals.evaluators import EvaluatorContext

from knowledge_map.evaluation.tasks import task_named
from knowledge_map.evaluation.tasks.policy_area_classification import (
    AgreedOnThePolicyAreas,
    ClassificationExpectation,
    ClassificationInput,
    ClassificationOutput,
    ClassifiedWithoutFailing,
)

HEALTH = "Health"
HOUSING = "Housing & Community Development"
LABOR = "Labor & Employment"


def _context(expected: ClassificationExpectation, output: ClassificationOutput):
    """One EvaluatorContext holding a silver answer and a model answer."""

    return EvaluatorContext(
        name="case",
        inputs=ClassificationInput(
            url="https://example.test/a", title="A", resolved_text="a"
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
            ClassificationExpectation(policy_areas=list(expected)),
            ClassificationOutput(policy_areas=list(returned), **output_kwargs),
        )
    )


def test_naming_exactly_the_silver_areas_scores_one_on_every_metric() -> None:
    scores = _scored(
        AgreedOnThePolicyAreas(), expected=(HEALTH, HOUSING), returned=(HOUSING, HEALTH)
    )

    assert scores == {
        "policy_area_precision": 1.0,
        "policy_area_recall": 1.0,
        "policy_area_f1": 1.0,
    }


def test_a_missed_area_costs_recall_and_leaves_precision_whole() -> None:
    scores = _scored(
        AgreedOnThePolicyAreas(), expected=(HEALTH, HOUSING), returned=(HEALTH,)
    )

    assert scores["policy_area_precision"] == 1.0
    assert scores["policy_area_recall"] == 0.5
    assert scores["policy_area_f1"] == pytest.approx(2 / 3)


def test_an_extra_area_costs_precision_and_leaves_recall_whole() -> None:
    """An article labeled with too much is distinguishable from one with too little."""

    scores = _scored(
        AgreedOnThePolicyAreas(), expected=(HEALTH,), returned=(HEALTH, LABOR)
    )

    assert scores["policy_area_precision"] == 0.5
    assert scores["policy_area_recall"] == 1.0
    assert scores["policy_area_f1"] == pytest.approx(2 / 3)


def test_an_article_with_no_areas_answered_with_none_is_a_pass() -> None:
    """Not an unscoreable case: agreeing that the vocabulary does not cover it
    is the right answer, and it scores as one."""

    scores = _scored(AgreedOnThePolicyAreas(), expected=(), returned=())

    assert scores == {
        "policy_area_precision": 1.0,
        "policy_area_recall": 1.0,
        "policy_area_f1": 1.0,
    }


def test_an_article_with_no_areas_answered_with_some_scores_zero() -> None:
    scores = _scored(AgreedOnThePolicyAreas(), expected=(), returned=(HEALTH,))

    assert scores == {
        "policy_area_precision": 0.0,
        "policy_area_recall": 0.0,
        "policy_area_f1": 0.0,
    }


def test_an_article_with_areas_answered_with_none_scores_zero() -> None:
    scores = _scored(AgreedOnThePolicyAreas(), expected=(HEALTH,), returned=())

    assert scores == {
        "policy_area_precision": 0.0,
        "policy_area_recall": 0.0,
        "policy_area_f1": 0.0,
    }


def test_disjoint_answers_score_zero_rather_than_failing() -> None:
    scores = _scored(AgreedOnThePolicyAreas(), expected=(HEALTH,), returned=(LABOR,))

    assert scores["policy_area_f1"] == 0.0


def test_an_area_named_twice_is_one_area() -> None:
    """The stage writes one node per area, so a repeat cannot cost precision."""

    scores = _scored(
        AgreedOnThePolicyAreas(), expected=(HEALTH,), returned=(HEALTH, HEALTH)
    )

    assert scores["policy_area_precision"] == 1.0


def test_a_failed_classification_is_scored_rather_than_raised() -> None:
    assert _scored(ClassifiedWithoutFailing(), expected=(HEALTH,), returned=()) is True
    assert (
        _scored(
            ClassifiedWithoutFailing(),
            expected=(HEALTH,),
            returned=(),
            failure_type="policy_area_classification_failure",
        )
        is False
    )


def test_a_failed_classification_still_scores_the_areas_it_did_not_return() -> None:
    """A failure stays in the population as a zero instead of leaving it."""

    scores = _scored(
        AgreedOnThePolicyAreas(),
        expected=(HEALTH,),
        returned=(),
        failure_type="policy_area_classification_failure",
    )

    assert scores["policy_area_recall"] == 0.0


def test_the_task_is_registered_with_its_own_types() -> None:
    task = task_named("policy_area_classification")

    assert task.input_type is ClassificationInput
    assert task.output_type is ClassificationExpectation
    assert task.data_set_stem == "policy_area_classification"
