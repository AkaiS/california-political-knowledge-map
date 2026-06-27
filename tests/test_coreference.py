import pytest
from coreference import replace_tags_with_entities

def test_replace_tags_with_entities_basic():
    # Test double quotes
    text = 'Gavin Newsom visited the school today. <ref entity="Gavin Newsom">He</ref> gave a speech.'
    expected = 'Gavin Newsom visited the school today. Gavin Newsom gave a speech.'
    assert replace_tags_with_entities(text) == expected

def test_replace_tags_with_entities_single_quotes():
    # Test single quotes
    text = "Gavin Newsom visited the school today. <ref entity='Gavin Newsom'>He</ref> gave a speech."
    expected = "Gavin Newsom visited the school today. Gavin Newsom gave a speech."
    assert replace_tags_with_entities(text) == expected

def test_replace_tags_with_entities_multiple():
    # Test multiple tags
    text = '<ref entity="Gavin Newsom">He</ref> visited the school. Then <ref entity="Democratic Party">they</ref> praised <ref entity="Gavin Newsom">him</ref>.'
    expected = 'Gavin Newsom visited the school. Then Democratic Party praised Gavin Newsom.'
    assert replace_tags_with_entities(text) == expected

def test_replace_tags_with_entities_no_tags():
    # Test no tags
    text = "Gavin Newsom visited the school today. He gave a speech."
    assert replace_tags_with_entities(text) == text

from pydantic_ai import ModelResponse, ToolCallPart, TextPart
from pydantic_ai.models.function import FunctionModel
from coreference import get_annotator_agent, get_critic_agent, CriticValidation

def test_get_annotator_agent():
    agent = get_annotator_agent(defer_check=True)
    
    def mock_model(messages, info):
        return ModelResponse(parts=[TextPart(content="Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> was happy.")])
        
    with agent.override(model=FunctionModel(mock_model)):
        result = agent.run_sync("Gavin Newsom signed a bill. He was happy.")
        assert result.output == "Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> was happy."

def test_get_critic_agent():
    agent = get_critic_agent(defer_check=True)
    
    def mock_model(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "is_valid": True,
                    "issues": []
                },
                tool_call_id="call_1"
            )
        ])
        
    with agent.override(model=FunctionModel(mock_model)):
        result = agent.run_sync("Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> was happy.")
        assert result.output.is_valid is True
        assert result.output.issues == []

from coreference import resolve_coreferences

def test_resolve_coreferences_immediate_success():
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    
    def mock_annotator(messages, info):
        return ModelResponse(parts=[TextPart(content="Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> was happy.")])
        
    def mock_critic(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "is_valid": True,
                    "issues": []
                },
                tool_call_id="call_1"
            )
        ])
        
    with annotator_agent.override(model=FunctionModel(mock_annotator)), critic_agent.override(model=FunctionModel(mock_critic)):
        result = resolve_coreferences(
            "Gavin Newsom signed a bill. He was happy.",
            annotator_agent=annotator_agent,
            critic_agent=critic_agent
        )
        assert result == "Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> was happy."

def test_resolve_coreferences_retry_success():
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    
    annotator_calls = 0
    def mock_annotator(messages, info):
        nonlocal annotator_calls
        annotator_calls += 1
        if annotator_calls == 1:
            return ModelResponse(parts=[TextPart(content="Gavin Newsom signed a bill. <ref entity=\"School\">He</ref> was happy.")])
        else:
            return ModelResponse(parts=[TextPart(content="Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> was happy.")])
            
    critic_calls = 0
    def mock_critic(messages, info):
        nonlocal critic_calls
        critic_calls += 1
        tool_name = info.output_tools[0].name
        if critic_calls == 1:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name=tool_name,
                    args={
                        "is_valid": False,
                        "issues": ["'He' refers to Gavin Newsom, not School."]
                    },
                    tool_call_id="call_1"
                )
            ])
        else:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name=tool_name,
                    args={
                        "is_valid": True,
                        "issues": []
                    },
                    tool_call_id="call_2"
                )
            ])
            
    with annotator_agent.override(model=FunctionModel(mock_annotator)), critic_agent.override(model=FunctionModel(mock_critic)):
        result = resolve_coreferences(
            "Gavin Newsom signed a bill. He was happy.",
            annotator_agent=annotator_agent,
            critic_agent=critic_agent
        )
        assert result == "Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> was happy."
        assert annotator_calls == 2
        assert critic_calls == 2

def test_resolve_coreferences_failure_fallback_original_text():
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    
    annotator_calls = 0
    def mock_annotator(messages, info):
        nonlocal annotator_calls
        annotator_calls += 1
        return ModelResponse(parts=[TextPart(content=f"Attempt {annotator_calls} annotation.")])
        
    def mock_critic(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "is_valid": False,
                    "issues": ["Always invalid."]
                },
                tool_call_id="call_1"
            )
        ])
        
    with annotator_agent.override(model=FunctionModel(mock_annotator)), critic_agent.override(model=FunctionModel(mock_critic)):
        result = resolve_coreferences(
            "Gavin Newsom signed a bill. He was happy.",
            annotator_agent=annotator_agent,
            critic_agent=critic_agent,
            max_retries=3
        )
        # Should execute 4 runs total (initial + 3 retries) and fall back to original text
        assert result == "Gavin Newsom signed a bill. He was happy."
        assert annotator_calls == 4


