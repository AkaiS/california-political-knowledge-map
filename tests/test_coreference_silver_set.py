"""The coreference silver set stays loadable and source-addressable."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from knowledge_map.adapters.coreference import (
    CoreferenceDeps,
    validate_mention_spans,
)
from knowledge_map.evaluation import EvaluationSplit, build_dataset, load_gold_set
from knowledge_map.schemas import MentionSpan

SILVER_SET_PATH = Path("evals/gold/coreference.yaml")


class CoreferenceCaseInput(BaseModel):
    """The full Story content shown to the production annotator."""

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    content: str


class CoreferenceExpectation(BaseModel):
    """Silver Mention Spans retained after model annotation and criticism."""

    model_config = ConfigDict(extra="forbid")

    mention_spans: list[MentionSpan]


class CoreferenceSilverMetadata(BaseModel):
    """Source and model provenance for one silver-labeled Story."""

    model_config = ConfigDict(extra="forbid")

    source_table: Literal["stories"]
    story_id: int
    label_quality: Literal["silver"]
    annotator_model: Literal["gpt-5.6-sol"]
    annotator_reasoning_effort: Literal["medium"]
    critic_model: Literal["gpt-5.6-sol"]
    critic_reasoning_effort: Literal["medium"]


def _load_silver_set():
    return load_gold_set(
        SILVER_SET_PATH,
        input_type=CoreferenceCaseInput,
        output_type=CoreferenceExpectation,
        metadata_type=CoreferenceSilverMetadata,
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
