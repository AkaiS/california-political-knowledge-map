"""The classification silver set stays loadable, article-addressable and in vocabulary."""

from collections import Counter
from pathlib import Path

from knowledge_map.adapters.coreference import CoreferenceDeps, substitute_mention_spans
from knowledge_map.evaluation import EvaluationSplit, build_dataset, load_gold_set
from knowledge_map.evaluation.tasks import task_named
from knowledge_map.ontology.news import POLICY_AREAS
from knowledge_map.schemas import PolicyAreaClassification

SILVER_SET_PATH = Path("evals/gold/policy_area_classification.yaml")
COREFERENCE_SILVER_SET_PATH = Path("evals/gold/coreference.yaml")
ANNOTATION_GUIDELINE_PATH = Path(
    "docs/evaluation/policy-area-classification-annotation.md"
)

#: The distribution the guideline records, as `areas in one article: articles`.
RECORDED_DISTRIBUTION = {0: 1, 1: 1, 2: 4, 3: 10, 4: 2, 5: 2}


def _load_silver_set(path: Path, task_name: str):
    """Load the file through the registered task's own types.

    Declaring a second set of types here would let the file drift from what
    `ca-map eval run policy_area_classification` validates it against, which
    is the one thing this test exists to prevent.
    """

    task = task_named(task_name)
    return load_gold_set(
        path,
        input_type=task.input_type,
        output_type=task.output_type,
        metadata_type=task.metadata_type,
    )


def test_the_silver_set_is_a_twenty_case_pydantic_evals_dataset() -> None:
    silver_set = _load_silver_set(SILVER_SET_PATH, "policy_area_classification")

    assert silver_set.task == "policy_area_classification"
    assert len(silver_set.cases) == 20

    dataset = build_dataset(silver_set, evaluators=())

    assert len(dataset.cases) == 20
    assert [case.name for case in dataset.cases] == [
        case.id for case in silver_set.cases
    ]


def test_every_case_id_addresses_one_source_article() -> None:
    """A case is a whole article, so its id is the article's own address."""

    silver_set = _load_silver_set(SILVER_SET_PATH, "policy_area_classification")

    assert all(case.id == case.task_input.url for case in silver_set.cases)
    assert len({case.id for case in silver_set.cases}) == 20
    assert len({case.metadata.story_id for case in silver_set.cases}) == 20


def test_the_cases_are_split_into_held_out_and_training() -> None:
    silver_set = _load_silver_set(SILVER_SET_PATH, "policy_area_classification")

    held_out = silver_set.split(EvaluationSplit.HELD_OUT)
    training = silver_set.split(EvaluationSplit.TRAINING)

    assert len(held_out) == 16
    assert len(training) == 4
    assert len(held_out) + len(training) == len(silver_set.cases)


def test_every_case_is_the_resolved_text_of_its_coreference_story() -> None:
    """The input is still what the stage reads: the article after substitution.

    A case is only meaningful as the text classification sees, so a change to
    the coreference silver labels or to substitution must fail here rather
    than quietly re-aim all twenty cases.
    """

    silver_set = _load_silver_set(SILVER_SET_PATH, "policy_area_classification")
    coreference_set = _load_silver_set(COREFERENCE_SILVER_SET_PATH, "coreference")
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


def test_every_silver_area_is_a_canonical_name_the_stage_can_return() -> None:
    """Silver the stage's output type could not express is silver no model can match."""

    silver_set = _load_silver_set(SILVER_SET_PATH, "policy_area_classification")
    canonical = {area.name for area in POLICY_AREAS}

    for case in silver_set.cases:
        areas = case.expected_output.policy_areas

        assert set(areas) <= canonical, case.id
        assert len(set(areas)) == len(areas), case.id
        # The closed vocabulary is what the classification schema admits.
        PolicyAreaClassification(policy_areas=areas)


def test_every_case_names_the_guideline_it_was_annotated_against() -> None:
    silver_set = _load_silver_set(SILVER_SET_PATH, "policy_area_classification")

    assert ANNOTATION_GUIDELINE_PATH.exists()
    for case in silver_set.cases:
        assert case.metadata.label_quality == "silver", case.id
        assert case.metadata.annotator_model == "claude-opus-5", case.id
        assert case.metadata.annotation_guideline == str(ANNOTATION_GUIDELINE_PATH)
        assert case.metadata.coreference_gold_set == str(COREFERENCE_SILVER_SET_PATH)


def test_an_article_the_vocabulary_does_not_cover_is_annotated_as_no_areas() -> None:
    """An empty expectation is an answer the set deliberately holds."""

    silver_set = _load_silver_set(SILVER_SET_PATH, "policy_area_classification")

    empty = [case for case in silver_set.cases if not case.expected_output.policy_areas]

    assert len(empty) == 1


def test_the_recorded_areas_per_article_distribution_matches_the_set() -> None:
    """The measurement issue 02 deferred, kept honest by the file it describes.

    No maximum is introduced anywhere: this records what twenty articles held
    so a later cap can be argued from it.
    """

    silver_set = _load_silver_set(SILVER_SET_PATH, "policy_area_classification")
    observed = Counter(
        len(case.expected_output.policy_areas) for case in silver_set.cases
    )

    assert dict(observed) == RECORDED_DISTRIBUTION

    guideline = ANNOTATION_GUIDELINE_PATH.read_text()
    for areas, articles in sorted(RECORDED_DISTRIBUTION.items()):
        assert f"| {areas} | {articles} |" in guideline

    total = sum(areas * articles for areas, articles in observed.items())
    assert total == 57
    assert max(observed) == 5
    assert guideline.count("no maximum") >= 1


def test_no_maximum_is_placed_on_the_areas_one_article_can_hold() -> None:
    """The schema the stage answers with sets no cap, and neither does the set."""

    every_area = [area.name for area in POLICY_AREAS]

    classification = PolicyAreaClassification(policy_areas=every_area)

    assert len(classification.policy_areas) == len(every_area)
