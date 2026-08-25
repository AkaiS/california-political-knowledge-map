"""The coreference silver set stays loadable and source-addressable."""

from pathlib import Path

from knowledge_map.adapters.coreference import (
    CoreferenceDeps,
    validate_mention_spans,
)
from knowledge_map.evaluation import EvaluationSplit, build_dataset, load_gold_set
from knowledge_map.evaluation.tasks import task_named

SILVER_SET_PATH = Path("evals/gold/coreference.yaml")


def _load_silver_set():
    """Load the file through the registered task's own types.

    Declaring a second set of types here would let the file drift from
    what `ca-map eval run coreference` validates it against, which is the
    one thing this test exists to prevent.
    """

    task = task_named("coreference")
    return load_gold_set(
        SILVER_SET_PATH,
        input_type=task.input_type,
        output_type=task.output_type,
        metadata_type=task.metadata_type,
    )


def test_coreference_silver_set_is_a_twenty_case_pydantic_evals_dataset() -> None:
    silver_set = _load_silver_set()

    assert silver_set.task == "coreference"
    assert len(silver_set.cases) == 20
    assert all(case.split is EvaluationSplit.HELD_OUT for case in silver_set.cases)
    assert all(case.id == case.task_input.url for case in silver_set.cases)

    dataset = build_dataset(silver_set, evaluators=())

    assert len(dataset.cases) == 20
    assert [case.name for case in dataset.cases] == [
        case.id for case in silver_set.cases
    ]


def test_every_silver_mention_span_locates_in_its_full_story() -> None:
    silver_set = _load_silver_set()

    for case in silver_set.cases:
        deps = CoreferenceDeps.for_content(case.task_input.content)
        mention_spans = case.expected_output.mention_spans
        validation = validate_mention_spans(
            deps.content,
            deps.sentences,
            mention_spans,
        )

        assert mention_spans, case.id
        assert validation.discards == [], case.id
        assert len(validation.valid_spans) == len(mention_spans), case.id
