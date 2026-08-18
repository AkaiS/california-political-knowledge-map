import pytest
from pydantic_ai import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from knowledge_map.adapters.coreference import (
    CoreferenceResolutionError,
    PydanticAICoreferenceAdapter,
    get_agent_metadata,
    get_annotator_agent,
)
from knowledge_map.schemas import MentionSpan


def mention_response(info, spans: list[dict]) -> ModelResponse:
    """Build the structured output tool call used by the annotator tests."""

    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args={"response": spans},
                tool_call_id="call_1",
            )
        ]
    )


def test_get_annotator_agent_returns_structured_mention_spans():
    agent = get_annotator_agent(defer_check=True)
    assert agent.output_type == list[MentionSpan]

    def mock_model(messages, info):
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "Gavin Newsom",
                }
            ],
        )

    with agent.override(model=FunctionModel(mock_model)):
        result = agent.run_sync("[1] Gavin Newsom signed a bill.\n[2] He was happy.")

    assert result.output == [
        MentionSpan(
            sentence_label="2",
            mention_text="He",
            canonical_entity_name="Gavin Newsom",
        )
    ]
    assert "<ref" not in get_agent_metadata(agent)["system_prompt"]


def test_adapter_numbers_sentences_and_applies_structured_mentions():
    content = "Gavin Newsom signed a bill. He was happy."
    annotator_agent = get_annotator_agent(defer_check=True)
    prompts: list[str] = []

    def mock_annotator(messages, info):
        prompts.append(messages[-1].parts[0].content)
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "Gavin Newsom",
                }
            ],
        )

    with annotator_agent.override(model=FunctionModel(mock_annotator)):
        result = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
        ).resolve(content)

    assert result == "Gavin Newsom signed a bill. Gavin Newsom was happy."
    assert len(prompts) == 1
    assert "[1] Gavin Newsom signed a bill. " in prompts[0]
    assert "[2] He was happy." in prompts[0]
    assert "Original text:" not in prompts[0]
    assert "Annotated text:" not in prompts[0]


def test_adapter_does_not_call_the_critic_in_the_mention_span_pass():
    content = "Gavin Newsom signed a bill. He was happy."
    annotator_agent = get_annotator_agent(defer_check=True)

    def mock_annotator(messages, info):
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "Gavin Newsom",
                }
            ],
        )

    class FailingCritic:
        def run_sync(self, *args, **kwargs):
            raise AssertionError("the critic is not part of issue 03")

    with annotator_agent.override(model=FunctionModel(mock_annotator)):
        result = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=FailingCritic(),
        ).resolve(content)

    assert result == "Gavin Newsom signed a bill. Gavin Newsom was happy."


def test_invalid_annotator_text_is_a_structured_output_failure():
    annotator_agent = get_annotator_agent(defer_check=True)

    def mock_annotator(messages, info):
        return ModelResponse(
            parts=[TextPart(content="Gavin Newsom signed a bill. He was happy.")]
        )

    with annotator_agent.override(model=FunctionModel(mock_annotator)):
        with pytest.raises(CoreferenceResolutionError) as exc_info:
            PydanticAICoreferenceAdapter(
                annotator_agent=annotator_agent,
            ).resolve("Gavin Newsom signed a bill. He was happy.")

    error = exc_info.value
    assert error.failure_type == "coreference_validation_failure"
    assert error.annotated_text == ""
    assert error.validation_issues


def test_discarded_mention_does_not_block_neighbouring_valid_mention():
    content = "Gavin Newsom signed a bill. He thanked her."
    annotator_agent = get_annotator_agent(defer_check=True)

    def mock_annotator(messages, info):
        return mention_response(
            info,
            [
                {
                    "sentence_label": "2",
                    "mention_text": "He",
                    "canonical_entity_name": "Gavin Newsom",
                },
                {
                    "sentence_label": "2",
                    "mention_text": "her",
                    "canonical_entity_name": "the committee",
                    "occurrence": 2,
                },
            ],
        )

    with annotator_agent.override(model=FunctionModel(mock_annotator)):
        result = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
        ).resolve(content)

    assert result == "Gavin Newsom signed a bill. Gavin Newsom thanked her."


def test_health_check_keeps_the_adapter_contract():
    annotator_agent = get_annotator_agent(defer_check=True)

    def mock_model(messages, info):
        return ModelResponse(parts=[TextPart(content="ok")])

    with annotator_agent.override(model=FunctionModel(mock_model)):
        adapter = PydanticAICoreferenceAdapter(annotator_agent=annotator_agent)
        assert adapter.health_check() is True


def test_health_check_returns_false_when_the_model_fails():
    annotator_agent = get_annotator_agent(defer_check=True)

    def mock_model(messages, info):
        raise RuntimeError("LLM connection failed")

    with annotator_agent.override(model=FunctionModel(mock_model)):
        adapter = PydanticAICoreferenceAdapter(annotator_agent=annotator_agent)
        assert adapter.health_check() is False
