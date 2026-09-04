"""The assignment silver set stays loadable, article-addressable and assignable.

The last of those is what this file adds over its classification sibling: a
case may only name a measure the stage could actually be given, and may only
assign it to an area the stage was actually handed, or it asks for an
assignment no model could ever make and every run loses the case.
"""

from collections import Counter
from pathlib import Path

from silver_sets import load_silver_set

from knowledge_map.adapters.coreference import CoreferenceDeps, substitute_mention_spans
from knowledge_map.core.topic_assignment import MEASURE_LABELS
from knowledge_map.evaluation import EvaluationSplit, build_dataset

SILVER_SET_PATH = Path("evals/silver/topic_assignment.yaml")
COREFERENCE_SILVER_SET_PATH = Path("evals/silver/coreference.yaml")
EXTRACTION_SILVER_SET_PATH = Path("evals/silver/extraction.yaml")
CLASSIFICATION_SILVER_SET_PATH = Path("evals/silver/policy_area_classification.yaml")
ANNOTATION_GUIDELINE_PATH = Path("docs/evaluation/topic-assignment-annotation.md")

#: The distribution the guideline records, as `pairs in one article: articles`.
RECORDED_DISTRIBUTION = {0: 7, 1: 2, 2: 4, 3: 3, 4: 4}


def _assignment_silver_set():
    return load_silver_set(SILVER_SET_PATH, "topic_assignment")


def test_the_silver_set_is_a_twenty_case_pydantic_evals_dataset() -> None:
    silver_set = _assignment_silver_set()

    assert silver_set.task == "topic_assignment"
    assert len(silver_set.cases) == 20

    dataset = build_dataset(silver_set, evaluators=())

    assert len(dataset.cases) == 20
    assert [case.name for case in dataset.cases] == [
        case.id for case in silver_set.cases
    ]


def test_every_case_id_addresses_one_source_article() -> None:
    """A case is a whole article, so its id is the article's own address."""

    silver_set = _assignment_silver_set()

    assert all(case.id == case.task_input.url for case in silver_set.cases)
    assert len({case.id for case in silver_set.cases}) == 20
    assert len({case.metadata.story_id for case in silver_set.cases}) == 20


def test_the_cases_are_split_into_held_out_and_training() -> None:
    silver_set = _assignment_silver_set()

    held_out = silver_set.split(EvaluationSplit.HELD_OUT)
    training = silver_set.split(EvaluationSplit.TRAINING)

    assert len(held_out) == 16
    assert len(training) == 4
    assert len(held_out) + len(training) == len(silver_set.cases)


def test_the_cases_are_the_twenty_stories_of_the_coreference_silver_set() -> None:
    """The input is still what the stage reads: the article after substitution.

    A case is only meaningful as the text assignment sees, so a change to the
    coreference silver labels or to substitution must fail here rather than
    quietly re-aim all twenty cases.
    """

    silver_set = _assignment_silver_set()
    coreference_set = load_silver_set(COREFERENCE_SILVER_SET_PATH, "coreference")
    stories = {case.task_input.url: case for case in coreference_set.cases}

    assert len(silver_set.cases) == len(coreference_set.cases)

    for case in silver_set.cases:
        story = stories[case.task_input.url]
        deps = CoreferenceDeps.for_content(story.task_input.content)
        resolved, discards = substitute_mention_spans(
            deps.content, deps.sentences, story.expected_output.mention_spans
        )

        assert discards == [], case.id
        assert case.task_input.resolved_text == resolved, case.id
        assert case.metadata.story_id == story.metadata.story_id, case.id


def test_every_case_is_given_the_areas_classification_found_for_it() -> None:
    """The areas half of the input is the other stage's silver answer.

    Assignment is given the classified set, and an assignment outside it is
    dropped before persistence.  Deciding the areas a second time here would
    let the two Silver Sets disagree about one article.
    """

    silver_set = _assignment_silver_set()
    classification_set = load_silver_set(
        CLASSIFICATION_SILVER_SET_PATH, "policy_area_classification"
    )
    classified = {
        case.task_input.url: case.expected_output.policy_areas
        for case in classification_set.cases
    }

    for case in silver_set.cases:
        assert case.task_input.policy_areas == classified[case.id], case.id


def test_every_measure_a_case_names_is_one_the_stage_could_be_given() -> None:
    """A case cannot ask for an assignment the stage could never make.

    The measure has to be one extraction produced for this article, or one the
    article itself names: anything else is a measure no run has a node for, so
    the case would cost every model a score it never had a chance at.
    """

    silver_set = _assignment_silver_set()
    extraction_set = load_silver_set(EXTRACTION_SILVER_SET_PATH, "extraction")

    extracted: dict[str, set[tuple[str, str]]] = {}
    for case in extraction_set.cases:
        found = extracted.setdefault(case.task_input.url, set())
        found.update(
            (node.name, node.label)
            for node in case.expected_output.nodes
            if node.label in MEASURE_LABELS
        )

    assert extraction_set.cases, "the extraction silver set is what anchors this"

    for case in silver_set.cases:
        article = case.task_input.resolved_text
        for measure in case.task_input.measures:
            named = (measure.name, measure.label)
            assert named in extracted.get(case.id, set()) or measure.name in article, (
                f"{case.id}: {named}"
            )


def test_every_measure_the_extraction_silver_set_produced_is_in_its_case() -> None:
    """The stage is given every measure the article's extractions produced.

    Dropping one would be annotating a different question than the stage is
    asked, and would let a case quietly excuse a model from a measure it will
    see in production.
    """

    silver_set = _assignment_silver_set()
    extraction_set = load_silver_set(EXTRACTION_SILVER_SET_PATH, "extraction")

    given = {
        case.id: {(measure.name, measure.label) for measure in case.task_input.measures}
        for case in silver_set.cases
    }

    for case in extraction_set.cases:
        for node in case.expected_output.nodes:
            if node.label not in MEASURE_LABELS:
                continue
            assert (node.name, node.label) in given[case.task_input.url], (
                f"{case.task_input.url}: {node.name}"
            )


def test_every_expected_pair_joins_a_given_measure_to_a_given_area() -> None:
    """An expectation the two drops would discard is an expectation no run can meet."""

    silver_set = _assignment_silver_set()

    for case in silver_set.cases:
        measures = {
            (measure.name, measure.label) for measure in case.task_input.measures
        }
        areas = set(case.task_input.policy_areas)
        for pair in case.expected_output.assignments:
            assert (pair.measure_name, pair.measure_label) in measures, case.id
            assert pair.policy_area in areas, case.id


def test_no_article_supports_the_same_pair_twice() -> None:
    """One topic edge per pair, so a repeated pair is one claim written twice."""

    silver_set = _assignment_silver_set()

    for case in silver_set.cases:
        pairs = [
            (pair.measure_name, pair.measure_label, pair.policy_area)
            for pair in case.expected_output.assignments
        ]

        assert len(set(pairs)) == len(pairs), case.id


def test_every_case_names_the_guideline_it_was_annotated_against() -> None:
    silver_set = _assignment_silver_set()

    assert ANNOTATION_GUIDELINE_PATH.exists()
    for case in silver_set.cases:
        assert case.metadata.label_quality == "silver", case.id
        assert case.metadata.annotator_model == "claude-opus-5", case.id
        assert case.metadata.annotation_guideline == str(ANNOTATION_GUIDELINE_PATH)
        assert case.metadata.coreference_silver_set == str(COREFERENCE_SILVER_SET_PATH)
        assert case.metadata.extraction_silver_set == str(EXTRACTION_SILVER_SET_PATH)


def test_an_article_supporting_no_pairs_is_annotated_as_no_assignments() -> None:
    """An empty expectation is an answer the set deliberately holds.

    Two kinds of article reach it: one that names no measure at all, and one
    that names a measure none of its areas belongs to.  Both are cases a model
    passes by assigning nothing.
    """

    silver_set = _assignment_silver_set()

    empty = [case for case in silver_set.cases if not case.expected_output.assignments]
    with_measures = [case for case in empty if case.task_input.measures]

    assert len(empty) == 7
    assert with_measures, "an article that names a measure and supports no pair"


def test_the_recorded_pairs_per_article_distribution_matches_the_set() -> None:
    """What twenty articles held, kept honest by the file it describes."""

    silver_set = _assignment_silver_set()
    observed = Counter(
        len(case.expected_output.assignments) for case in silver_set.cases
    )

    assert dict(observed) == RECORDED_DISTRIBUTION

    guideline = ANNOTATION_GUIDELINE_PATH.read_text()
    for pairs, articles in sorted(RECORDED_DISTRIBUTION.items()):
        assert f"| {pairs} | {articles} |" in guideline

    total = sum(pairs * articles for pairs, articles in observed.items())
    assert total == 35
    assert max(observed) == 4

    # The other half of what the guideline records: the measures those pairs
    # were drawn from, and how many of them took any area at all.
    measures = sum(len(case.task_input.measures) for case in silver_set.cases)
    assigned = {
        (case.id, pair.measure_name, pair.measure_label)
        for case in silver_set.cases
        for pair in case.expected_output.assignments
    }

    assert measures == 25
    assert len(assigned) == 23
