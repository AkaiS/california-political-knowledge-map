"""The extraction silver set stays loadable, chunk-addressable and on-ontology."""

from pathlib import Path

from knowledge_map.adapters.coreference import CoreferenceDeps, substitute_mention_spans
from knowledge_map.evaluation import EvaluationSplit, build_dataset, load_gold_set
from knowledge_map.evaluation.tasks import task_named
from knowledge_map.evaluation.tasks.extraction import silver_extraction_result
from knowledge_map.ontology.extraction_conformance import conform_extraction_result
from knowledge_map.ontology.news import EXTRACTED_LABELS
from knowledge_map.utils.chunking import chunk_article

SILVER_SET_PATH = Path("evals/gold/extraction.yaml")
COREFERENCE_SILVER_SET_PATH = Path("evals/gold/coreference.yaml")
ANNOTATION_GUIDELINE_PATH = Path("docs/evaluation/extraction-annotation.md")


def _load_silver_set(path: Path, task_name: str):
    """Load the file through the registered task's own types.

    Declaring a second set of types here would let the file drift from
    what `ca-map eval run extraction` validates it against, which is the
    one thing this test exists to prevent.
    """

    task = task_named(task_name)
    return load_gold_set(
        path,
        input_type=task.input_type,
        output_type=task.output_type,
        metadata_type=task.metadata_type,
    )


def test_extraction_silver_set_is_a_fifty_case_pydantic_evals_dataset() -> None:
    silver_set = _load_silver_set(SILVER_SET_PATH, "extraction")

    assert silver_set.task == "extraction"
    assert len(silver_set.cases) == 50
    assert all(case.split is EvaluationSplit.HELD_OUT for case in silver_set.cases)
    assert all(
        case.id == f"{case.task_input.url}#chunk-{case.task_input.chunk_index}"
        for case in silver_set.cases
    )

    dataset = build_dataset(silver_set, evaluators=())

    assert len(dataset.cases) == 50
    assert [case.name for case in dataset.cases] == [
        case.id for case in silver_set.cases
    ]


def test_every_case_is_a_chunk_of_its_resolved_coreference_story() -> None:
    """The input text is still what chunking cuts from the resolved Story.

    A case is only meaningful as the text extraction sees, so a change to
    chunk size, to the overlap refinery, or to the coreference silver
    labels must fail here rather than quietly re-aim all fifty cases.
    """

    silver_set = _load_silver_set(SILVER_SET_PATH, "extraction")
    coreference_set = _load_silver_set(COREFERENCE_SILVER_SET_PATH, "coreference")
    stories = {case.task_input.url: case for case in coreference_set.cases}

    chunks_by_url: dict[str, list] = {}
    for case in silver_set.cases:
        story = stories[case.task_input.url]
        if story.task_input.url not in chunks_by_url:
            deps = CoreferenceDeps.for_content(story.task_input.content)
            resolved, discards = substitute_mention_spans(
                deps.content, deps.sentences, story.expected_output.mention_spans
            )
            assert discards == [], story.id
            chunks_by_url[story.task_input.url] = chunk_article(resolved)

        chunks = chunks_by_url[case.task_input.url]
        assert case.metadata.chunk_count == len(chunks), case.id
        assert chunks[case.task_input.chunk_index].text == case.task_input.text, case.id


def test_every_silver_label_survives_news_ontology_conformance() -> None:
    """Silver the adapter's conformance would reduce is silver no model can match."""

    silver_set = _load_silver_set(SILVER_SET_PATH, "extraction")

    for case in silver_set.cases:
        expected = silver_extraction_result(case.expected_output)
        outcome = conform_extraction_result(expected, chunk_id=case.id)

        assert outcome.drops == (), case.id
        assert outcome.result.model_dump() == expected.model_dump(), case.id


def test_the_guideline_asks_only_for_labels_extraction_is_responsible_for() -> None:
    """A guideline asking for more than the ontology admits re-annotates itself.

    Every case names this file, so a label it still asks for is one a later
    pass would annotate and conformance would then drop.
    """

    guideline = ANNOTATION_GUIDELINE_PATH.read_text()

    assert "PolicyArea" not in guideline
    assert "ABOUT_TOPIC" not in guideline
    assert "DISCUSSES_TOPIC" not in guideline
    # It says where the question went instead of leaving it open.
    assert "Policy Area Classification" in guideline
    for label in sorted(EXTRACTED_LABELS):
        assert f"`{label}`" in guideline, label


def test_the_fifty_chunks_are_drawn_from_all_twenty_stories() -> None:
    silver_set = _load_silver_set(SILVER_SET_PATH, "extraction")

    story_ids = {case.metadata.story_id for case in silver_set.cases}
    chunk_addresses = {
        (case.metadata.story_id, case.metadata.chunk_index)
        for case in silver_set.cases
    }

    assert len(story_ids) == 20
    assert len(chunk_addresses) == 50
