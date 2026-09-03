import json

import pytest
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from knowledge_map.adapters.coreference import (
    CoreferenceResolutionError,
    PydanticAICoreferenceAdapter,
    get_annotator_agent,
    get_critic_agent,
)
from knowledge_map.adapters.dlq import LocalFileDLQAdapter
from knowledge_map.core.pipeline import StoryPipeline
from knowledge_map.schemas import (
    AdherenceReport,
    ArticleChunk,
    ExtractionResult,
    Node,
    SourceArticle,
)


def structured_response(info, value: list[dict]) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args={"response": value},
                tool_call_id="call_issue_05",
            )
        ]
    )


def make_adapter(
    mentions: list[dict],
    verdicts: list[dict],
    *,
    max_critic_rounds: int = 0,
    annotator_retries: int = 3,
) -> PydanticAICoreferenceAdapter:
    return _OverriddenAdapter(
        mentions,
        verdicts,
        max_critic_rounds=max_critic_rounds,
        annotator_retries=annotator_retries,
    )


class _OverriddenAdapter(PydanticAICoreferenceAdapter):
    """Keep FunctionModel overrides active for a test-created adapter."""

    def __init__(self, mentions, verdicts, *, max_critic_rounds, annotator_retries=3):
        annotator = get_annotator_agent(
            defer_check=True,
            retries=annotator_retries,
        )
        critic = get_critic_agent(defer_check=True)

        annotator_calls: list[int] = []

        def mock_annotator(messages, info):
            annotator_calls.append(1)
            return structured_response(info, mentions)

        def mock_critic(messages, info):
            return structured_response(info, verdicts)

        self.annotator_calls = annotator_calls
        super().__init__(
            annotator_agent=annotator,
            critic_agent=critic,
            max_critic_rounds=max_critic_rounds,
        )
        self._annotator_model = FunctionModel(mock_annotator)
        self._critic_model = FunctionModel(mock_critic)

    def resolve(self, content: str):
        with (
            self.annotator_agent.override(model=self._annotator_model),
            self.critic_agent.override(model=self._critic_model),
        ):
            return super().resolve(content)


def test_empty_annotator_output_is_a_distinct_zero_survivor_failure():
    adapter = make_adapter([], [])

    with pytest.raises(CoreferenceResolutionError) as exc_info:
        adapter.resolve("Gavin Newsom signed a bill.")

    error = exc_info.value
    assert error.failure_type == "no_mentions_returned"
    # An article with nothing to resolve is a real outcome, not a mistake the
    # annotator is asked to correct.
    assert len(adapter.annotator_calls) == 1
    assert error.resolution_run.outcomes == []
    assert error.resolution_run.discarded_proportion == 0.0
    assert error.resolution_run.sentences[0].text == "Gavin Newsom signed a bill."


def test_validation_discard_of_every_span_has_its_own_failure_type():
    adapter = make_adapter(
        [
            {
                "sentence_label": "99",
                "mention_text": "He",
                "canonical_entity_name": "Gavin Newsom",
            }
        ],
        [],
    )

    with pytest.raises(CoreferenceResolutionError) as exc_info:
        adapter.resolve("Gavin Newsom signed a bill.")

    error = exc_info.value
    assert error.failure_type == "all_mentions_discarded"
    run = error.resolution_run
    assert [outcome.outcome for outcome in run.outcomes] == ["discarded"]
    assert run.outcomes[0].stage == "validation"
    assert run.discarded_proportion == 1.0


def test_a_persistently_unlocatable_annotator_exhausts_its_correction_budget():
    """`all_mentions_discarded` is now reached only after the corrections fail.

    The annotator is asked again for as long as its structured-output retry
    budget allows, and the Coreference Resolution Run's round count records
    those attempts, so an exhausted run is not mistaken for a first-response
    failure.
    """

    unlocatable = [
        {
            "sentence_label": "99",
            "mention_text": "He",
            "canonical_entity_name": "Gavin Newsom",
        }
    ]
    adapter = make_adapter(unlocatable, [], annotator_retries=3)

    with pytest.raises(CoreferenceResolutionError) as exc_info:
        adapter.resolve("Gavin Newsom signed a bill.")

    error = exc_info.value
    assert error.failure_type == "all_mentions_discarded"
    # One first answer plus the three corrections the budget allows.
    assert len(adapter.annotator_calls) == 4
    assert error.resolution_run.retry_count == 3
    assert error.retry_count == 3


def test_an_annotator_with_no_correction_budget_fails_on_its_first_response():
    """Without a retry budget there is nothing to distinguish but the count."""

    unlocatable = [
        {
            "sentence_label": "99",
            "mention_text": "He",
            "canonical_entity_name": "Gavin Newsom",
        }
    ]
    adapter = make_adapter(unlocatable, [], annotator_retries=0)

    with pytest.raises(CoreferenceResolutionError) as exc_info:
        adapter.resolve("Gavin Newsom signed a bill.")

    assert exc_info.value.failure_type == "all_mentions_discarded"
    assert len(adapter.annotator_calls) == 1
    assert exc_info.value.resolution_run.retry_count == 0


def test_critic_rejection_of_every_valid_span_has_its_own_failure_type():
    adapter = make_adapter(
        [
            {
                "sentence_label": "2",
                "mention_text": "He",
                "canonical_entity_name": "the committee",
            }
        ],
        [
            {
                "sentence_label": "2",
                "mention_text": "He",
                "accepted": False,
                "reason": "The sentence refers to Gavin Newsom.",
            }
        ],
    )

    with pytest.raises(CoreferenceResolutionError) as exc_info:
        adapter.resolve("Gavin Newsom signed a bill. He was happy.")

    error = exc_info.value
    assert error.failure_type == "all_mentions_rejected"
    run = error.resolution_run
    assert [outcome.outcome for outcome in run.outcomes] == ["rejected"]
    assert run.outcomes[0].stage == "critic"
    assert run.outcomes[0].reason == "The sentence refers to Gavin Newsom."
    assert run.discarded_proportion == 1.0


def test_partial_discard_completes_and_records_outcomes_and_proportion():
    adapter = make_adapter(
        [
            {
                "sentence_label": "2",
                "mention_text": "He",
                "canonical_entity_name": "Gavin Newsom",
            },
            {
                "sentence_label": "2",
                "mention_text": "her",
                "occurrence": 2,
                "canonical_entity_name": "the committee",
            },
        ],
        [
            {
                "sentence_label": "2",
                "mention_text": "He",
                "accepted": True,
            }
        ],
    )

    run = adapter.resolve("Gavin Newsom signed a bill. He thanked her.")

    assert run.resolved_text == "Gavin Newsom signed a bill. Gavin Newsom thanked her."
    assert [outcome.outcome for outcome in run.outcomes] == [
        "discarded",
        "accepted",
    ]
    assert run.discarded_proportion == 0.5
    # One locatable Mention Span is enough: the unlocatable neighbour stays a
    # recorded discard rather than costing the answer a correction round.
    assert len(adapter.annotator_calls) == 1
    assert run.retry_count == 0


class _Database:
    def ingest_article(self, article):
        pass

    def ingest_chunk(self, article, chunk, embedding):
        pass

    def ingest_chunk_extraction(self, chunk_id, extraction, bill_sessions=None, event_dates=None):
        pass

    def ingest_article_topics(self, article, policy_areas, assignments=None, bill_sessions=None):
        pass


class _PolicyAreas:
    def classify(self, resolved_text: str) -> list[str]:
        return []


class _Embedding:
    def process_chunks(self, chunks: list[ArticleChunk]) -> list[list[float]]:
        return [[0.1] for _ in chunks]


class _Extraction:
    @property
    def adherence_report(self) -> AdherenceReport:
        return AdherenceReport()

    def reset_adherence_report(self) -> None:
        pass

    def extract(self, chunk_text: str) -> ExtractionResult:
        return ExtractionResult(
            nodes=[Node(name="Gavin Newsom", label="Politician")],
            relationships=[],
        )


class _Status:
    def __init__(self):
        self.updates = []

    def update_status(self, url: str, status: str) -> None:
        self.updates.append((url, status))


@pytest.mark.parametrize(
    ("mentions", "verdicts", "failure_type"),
    [
        ([], [], "no_mentions_returned"),
        (
            [
                {
                    "sentence_label": "99",
                    "mention_text": "He",
                    "canonical_entity_name": "Gavin Newsom",
                }
            ],
            [],
            "all_mentions_discarded",
        ),
        (
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "the committee",
                }
            ],
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "accepted": False,
                    "reason": "Wrong antecedent.",
                }
            ],
            "all_mentions_rejected",
        ),
    ],
)
def test_zero_survivor_failures_reach_failed_dlq_with_replayable_payload(
    tmp_path,
    mentions,
    verdicts,
    failure_type,
):
    status = _Status()
    adapter = make_adapter(mentions, verdicts)
    dlq = LocalFileDLQAdapter(directory=str(tmp_path / "dlq"))
    article = SourceArticle(
        url=f"https://example.com/{failure_type}",
        title="A coreference failure",
        content="Gavin Newsom signed a bill. He was happy.",
    )
    pipeline = StoryPipeline(
        db_adapter=_Database(),
        embedding_adapter=_Embedding(),
        coreference_adapter=adapter,
        extraction_adapter=_Extraction(),
        policy_area_adapter=_PolicyAreas(),
        status_tracker=status,
        dlq_adapter=dlq,
    )

    with pytest.raises(CoreferenceResolutionError) as exc_info:
        pipeline.run(article)

    assert exc_info.value.failure_type == failure_type
    assert status.updates == [(article.url, "PROCESSING"), (article.url, "FAILED_DLQ")]
    files = list((tmp_path / "dlq" / "coreference").glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert "annotated_text" not in payload
    assert payload["failure_type"] == failure_type
    assert payload["original_text"] == article.content
    assert payload["validation_issues"]
    # The run is written once, as a single nested record.
    assert set(payload) == {
        "url",
        "title",
        "original_text",
        "validation_issues",
        "failure_type",
        "timestamp",
        "retry_count",
        "metadata",
        "resolution_run",
    }
    run_payload = payload["resolution_run"]
    assert run_payload["failure_type"] == failure_type
    assert run_payload["sentences"][0]["label"] == "1"
    assert len(run_payload["mention_spans"]) == len(mentions)


def test_an_exhausted_correction_is_visible_in_the_dead_letter_queue_record(tmp_path):
    """The record says a correction was attempted before it was archived.

    A Dead Letter Queue reader has to tell a run that failed on its first
    response from one that was asked again and kept getting it wrong, because
    only the second is evidence that the annotator cannot recover.
    """

    status = _Status()
    adapter = make_adapter(
        [
            {
                "sentence_label": "99",
                "mention_text": "He",
                "canonical_entity_name": "Gavin Newsom",
            }
        ],
        [],
        annotator_retries=3,
    )
    dlq = LocalFileDLQAdapter(directory=str(tmp_path / "dlq"))
    article = SourceArticle(
        url="https://example.com/exhausted-correction",
        title="An annotator that could not be corrected",
        content="Gavin Newsom signed a bill. He was happy.",
    )
    pipeline = StoryPipeline(
        db_adapter=_Database(),
        embedding_adapter=_Embedding(),
        coreference_adapter=adapter,
        extraction_adapter=_Extraction(),
        policy_area_adapter=_PolicyAreas(),
        status_tracker=status,
        dlq_adapter=dlq,
    )

    with pytest.raises(CoreferenceResolutionError) as exc_info:
        pipeline.run(article)

    assert exc_info.value.failure_type == "all_mentions_discarded"
    assert status.updates == [(article.url, "PROCESSING"), (article.url, "FAILED_DLQ")]
    files = list((tmp_path / "dlq" / "coreference").glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["failure_type"] == "all_mentions_discarded"
    assert payload["retry_count"] == 3
    assert payload["resolution_run"]["retry_count"] == 3
    # The reasons the annotator was given are the ones the record carries.
    assert any("99" in issue for issue in payload["validation_issues"])
