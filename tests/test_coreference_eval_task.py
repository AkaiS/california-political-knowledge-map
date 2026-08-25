"""The coreference evaluators score the four things they claim to score."""

import pytest
from pydantic_evals.evaluators import EvaluatorContext

from knowledge_map.evaluation.tasks import task_named
from knowledge_map.evaluation.tasks.coreference import (
    AgreedOnTheCanonicalEntity,
    CoreferenceExpectation,
    CoreferenceInput,
    CoreferenceOutput,
    FoundTheSilverMentionSpans,
    MatchedTheSilverClustering,
    ResolvedWithoutFailing,
    entity_by_identity,
    normalize_entity_name,
)
from knowledge_map.schemas import MentionSpan


def _span(label: str, text: str, entity: str, occurrence: int = 1) -> MentionSpan:
    return MentionSpan(
        sentence_label=label,
        mention_text=text,
        occurrence=occurrence,
        canonical_entity_name=entity,
    )


def _context(expected: list[MentionSpan], output: CoreferenceOutput):
    """One EvaluatorContext holding a silver answer and a model answer."""

    return EvaluatorContext(
        name="case",
        inputs=CoreferenceInput(url="https://example.test/a", title="A", content="a"),
        metadata=None,
        expected_output=CoreferenceExpectation(mention_spans=expected),
        output=output,
        duration=0.0,
        _span_tree=None,
        attributes={},
        metrics={},
    )


def _scored(evaluator, expected, produced, **output_kwargs):
    return evaluator.evaluate(
        _context(expected, CoreferenceOutput(mention_spans=produced, **output_kwargs))
    )


# --- the task is registered and reachable from the CLI -----------------------


def test_coreference_is_a_registered_task_with_its_four_evaluators() -> None:
    task = task_named("coreference")

    assert task.name == "coreference"
    assert task.collect is None
    assert [type(evaluator).__name__ for evaluator in task.evaluators] == [
        "FoundTheSilverMentionSpans",
        "AgreedOnTheCanonicalEntity",
        "MatchedTheSilverClustering",
        "ResolvedWithoutFailing",
    ]


# --- span detection ----------------------------------------------------------


def test_an_identical_answer_scores_one_everywhere() -> None:
    spans = [_span("1", "He", "Steve Hilton"), _span("2", "Cameron", "David Cameron")]

    assert _scored(FoundTheSilverMentionSpans(), spans, list(spans)) == {
        "span_precision": 1.0,
        "span_recall": 1.0,
        "span_f1": 1.0,
    }


def test_a_missed_mention_costs_recall_and_leaves_precision_whole() -> None:
    expected = [_span("1", "He", "X"), _span("2", "him", "X")]

    scored = _scored(FoundTheSilverMentionSpans(), expected, [_span("1", "He", "X")])

    assert scored["span_precision"] == 1.0
    assert scored["span_recall"] == 0.5


def test_a_spurious_mention_costs_precision_and_leaves_recall_whole() -> None:
    expected = [_span("1", "He", "X")]
    produced = [_span("1", "He", "X"), _span("3", "they", "Y")]

    scored = _scored(FoundTheSilverMentionSpans(), expected, produced)

    assert scored["span_recall"] == 1.0
    assert scored["span_precision"] == 0.5


def test_the_occurrence_is_part_of_the_location() -> None:
    """The second "He" in a sentence is a different mention from the first."""

    expected = [_span("1", "He", "X", occurrence=2)]

    scored = _scored(
        FoundTheSilverMentionSpans(), expected, [_span("1", "He", "X", occurrence=1)]
    )

    assert scored["span_recall"] == 0.0


def test_the_entity_name_is_not_part_of_the_location() -> None:
    """Detection is scored before naming, so a wrong entity still counts."""

    scored = _scored(
        FoundTheSilverMentionSpans(),
        [_span("1", "He", "Steve Hilton")],
        [_span("1", "He", "David Cameron")],
    )

    assert scored["span_recall"] == 1.0
    assert scored["span_precision"] == 1.0


def test_a_failed_run_scores_zero_rather_than_disappearing() -> None:
    scored = _scored(
        FoundTheSilverMentionSpans(),
        [_span("1", "He", "X")],
        [],
        failure_type="all_mentions_rejected",
    )

    assert scored == {"span_precision": 0.0, "span_recall": 0.0, "span_f1": 0.0}


# --- entity naming -----------------------------------------------------------


def test_naming_is_scored_only_over_the_mentions_both_sides_found() -> None:
    expected = [_span("1", "He", "Steve Hilton"), _span("2", "him", "Steve Hilton")]
    produced = [_span("1", "He", "Steve Hilton")]

    # 1 of 1 shared, not 1 of 2: the mention it never found is a detection
    # miss and is charged to recall, not to naming.
    assert _scored(AgreedOnTheCanonicalEntity(), expected, produced) == {
        "entity_accuracy": 1.0
    }


def test_a_wrong_entity_on_a_found_mention_is_scored_as_disagreement() -> None:
    expected = [_span("1", "He", "Steve Hilton"), _span("2", "He", "Steve Hilton")]
    produced = [_span("1", "He", "Steve Hilton"), _span("2", "He", "David Cameron")]

    assert _scored(AgreedOnTheCanonicalEntity(), expected, produced) == {
        "entity_accuracy": 0.5
    }


@pytest.mark.parametrize("written", ["Steve Hilton", "steve hilton", "Steve  Hilton"])
def test_case_and_whitespace_are_not_a_disagreement(written: str) -> None:
    assert _scored(
        AgreedOnTheCanonicalEntity(),
        [_span("1", "He", "Steve Hilton")],
        [_span("1", "He", written)],
    ) == {"entity_accuracy": 1.0}


def test_a_shortened_name_is_a_disagreement_here() -> None:
    """Left to the clustering evaluator, which reads no names at all."""

    assert _scored(
        AgreedOnTheCanonicalEntity(),
        [_span("1", "He", "Steve Hilton")],
        [_span("1", "He", "Hilton")],
    ) == {"entity_accuracy": 0.0}


def test_no_shared_mention_is_unscored_rather_than_zero() -> None:
    assert (
        _scored(
            AgreedOnTheCanonicalEntity(),
            [_span("1", "He", "X")],
            [_span("9", "they", "Y")],
        )
        is None
    )


# --- clustering --------------------------------------------------------------


def test_renaming_every_cluster_consistently_still_matches_the_partition() -> None:
    expected = [
        _span("1", "He", "Steve Hilton"),
        _span("2", "him", "Steve Hilton"),
        _span("3", "Cameron", "David Cameron"),
    ]
    produced = [
        _span("1", "He", "Hilton"),
        _span("2", "him", "Hilton"),
        _span("3", "Cameron", "Cameron"),
    ]

    assert _scored(MatchedTheSilverClustering(), expected, produced) == {
        "cluster_precision": 1.0,
        "cluster_recall": 1.0,
        "cluster_f1": 1.0,
    }
    # The same answer, scored by name, looks like a total failure.
    assert _scored(AgreedOnTheCanonicalEntity(), expected, produced) == {
        "entity_accuracy": 0.0
    }


def test_merging_two_people_into_one_cluster_costs_precision() -> None:
    expected = [
        _span("1", "He", "Steve Hilton"),
        _span("2", "him", "Steve Hilton"),
        _span("3", "Cameron", "David Cameron"),
    ]
    produced = [
        _span("1", "He", "Hilton"),
        _span("2", "him", "Hilton"),
        _span("3", "Cameron", "Hilton"),
    ]

    scored = _scored(MatchedTheSilverClustering(), expected, produced)

    # Every mention is in one predicted cluster of 3.  Precision per mention:
    # 2/3, 2/3, 1/3.  Recall: the silver clusters are recovered whole.
    assert scored["cluster_precision"] == pytest.approx(5 / 9)
    assert scored["cluster_recall"] == 1.0


def test_splitting_one_person_across_two_clusters_costs_recall() -> None:
    expected = [
        _span("1", "He", "Steve Hilton"),
        _span("2", "him", "Steve Hilton"),
        _span("3", "his", "Steve Hilton"),
    ]
    produced = [
        _span("1", "He", "Hilton"),
        _span("2", "him", "Hilton"),
        _span("3", "his", "The candidate"),
    ]

    scored = _scored(MatchedTheSilverClustering(), expected, produced)

    assert scored["cluster_precision"] == 1.0
    assert scored["cluster_recall"] == pytest.approx(5 / 9)


def test_clustering_ignores_mentions_only_one_side_found() -> None:
    """A mention the model never proposed belongs to no predicted cluster."""

    expected = [
        _span("1", "He", "Steve Hilton"),
        _span("2", "him", "Steve Hilton"),
        _span("7", "she", "Rachel Whetstone"),
    ]
    produced = [_span("1", "He", "Hilton"), _span("2", "him", "Hilton")]

    assert _scored(MatchedTheSilverClustering(), expected, produced) == {
        "cluster_precision": 1.0,
        "cluster_recall": 1.0,
        "cluster_f1": 1.0,
    }


def test_clustering_is_unscored_when_nothing_overlaps() -> None:
    assert (
        _scored(MatchedTheSilverClustering(), [_span("1", "He", "X")], [])
        is None
    )


# --- run health --------------------------------------------------------------


def test_a_run_that_produced_spans_resolved() -> None:
    assert _scored(ResolvedWithoutFailing(), [], [_span("1", "He", "X")]) is True


def test_a_run_that_raised_did_not_resolve() -> None:
    assert (
        _scored(
            ResolvedWithoutFailing(),
            [_span("1", "He", "X")],
            [],
            failure_type="coreference_validation_failure",
        )
        is False
    )


def test_an_empty_answer_that_did_not_fail_still_counts_as_resolved() -> None:
    """A Story with no references legitimately yields no Mention Spans."""

    assert _scored(ResolvedWithoutFailing(), [], []) is True


# --- indexing ----------------------------------------------------------------


def test_two_entities_claiming_one_location_collapse_to_the_last() -> None:
    """Matching `ResolutionState`, whose outcome map does the same thing."""

    indexed = entity_by_identity(
        [_span("1", "He", "Steve Hilton"), _span("1", "He", "David Cameron")]
    )

    assert len(indexed) == 1
    assert next(iter(indexed.values())) == normalize_entity_name("David Cameron")
