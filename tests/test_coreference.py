import pytest
from knowledge_map.adapters.coreference import replace_tags_with_entities

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
from knowledge_map.adapters.coreference import get_annotator_agent, get_critic_agent
from knowledge_map.schemas import CriticValidation

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

from knowledge_map.adapters.coreference import resolve_coreferences

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


from knowledge_map.adapters.coreference import PydanticAICoreferenceAdapter

def test_pydantic_ai_coreference_adapter_success():
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
        adapter = PydanticAICoreferenceAdapter(
            annotator_agent=annotator_agent,
            critic_agent=critic_agent
        )
        result = adapter.resolve("Gavin Newsom signed a bill. He was happy.")
        assert result == "Gavin Newsom signed a bill. Gavin Newsom was happy."


def test_resolve_coreferences_structural_mismatch_retry_success():
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    
    annotator_calls = 0
    feedback_received = []
    
    def mock_annotator(messages, info):
        nonlocal annotator_calls
        annotator_calls += 1
        # Track if we received feedback about structural identity check
        if len(messages) > 1:
            last_part = messages[-1].parts[-1]
            if hasattr(last_part, "content"):
                feedback_received.append(last_part.content)
        
        if annotator_calls == 1:
            # Structurally modified: missing words
            return ModelResponse(parts=[TextPart(content="Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> happy.")])
        else:
            # Structurally correct
            return ModelResponse(parts=[TextPart(content="Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> was happy.")])
            
    critic_calls = 0
    def mock_critic(messages, info):
        nonlocal critic_calls
        critic_calls += 1
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
            critic_agent=critic_agent,
            max_retries=3
        )
        assert result == "Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> was happy."
        assert annotator_calls == 2
        # Critic must only be called once, because the first attempt bypassed it due to structural mismatch
        assert critic_calls == 1
        assert len(feedback_received) == 1
        assert "structural" in feedback_received[0].lower() or "structure" in feedback_received[0].lower()


def test_resolve_coreferences_structural_mismatch_fallback():
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    
    annotator_calls = 0
    def mock_annotator(messages, info):
        nonlocal annotator_calls
        annotator_calls += 1
        # Always structurally mismatching
        return ModelResponse(parts=[TextPart(content="Newsom signed bill.")])
        
    critic_calls = 0
    def mock_critic(messages, info):
        nonlocal critic_calls
        critic_calls += 1
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
            critic_agent=critic_agent,
            max_retries=3
        )
        # Should fall back to original text since all attempts failed structural checks
        assert result == "Gavin Newsom signed a bill. He was happy."
        assert annotator_calls == 4
        assert critic_calls == 0


from knowledge_map.adapters.coreference import (
    strip_ref_tags,
    normalize_whitespace,
    check_structural_identity
)

def test_strip_ref_tags():
    # Test double quotes
    assert strip_ref_tags('<ref entity="Gavin Newsom">He</ref> signed a bill.') == "He signed a bill."
    # Test single quotes
    assert strip_ref_tags("<ref entity='Gavin Newsom'>He</ref> signed.") == "He signed."
    # Test with spacing around attribute
    assert strip_ref_tags("<ref   entity  =  \"Gavin Newsom\" >He</ref> signed.") == "He signed."
    # Test multiple tags
    text = '<ref entity="Gavin Newsom">He</ref> saw <ref entity="Jerry Brown">him</ref>.'
    assert strip_ref_tags(text) == "He saw him."
    # Test no tags
    assert strip_ref_tags("He signed a bill.") == "He signed a bill."

def test_normalize_whitespace():
    # Test trimming
    assert normalize_whitespace("  hello  ") == "hello"
    # Test multi-space collapsing
    assert normalize_whitespace("hello    world") == "hello world"
    # Test newline collapsing
    assert normalize_whitespace("hello\n\nworld\nnew  line") == "hello world new line"

def test_check_structural_identity():
    # Identical text
    assert check_structural_identity("He signed a bill.", "He signed a bill.") is True
    # Structurally matching with different tags
    assert check_structural_identity(
        "He signed a bill.",
        '<ref entity="Gavin Newsom">He</ref> signed a bill.'
    ) is True
    # Structurally matching with varying whitespace
    assert check_structural_identity(
        "He signed\n a bill.",
        ' <ref entity="Gavin Newsom">He</ref>   signed a bill. '
    ) is True
    # Structural mismatch (extra word)
    assert check_structural_identity(
        "He signed a bill.",
        '<ref entity="Gavin Newsom">He</ref> signed a new bill.'
    ) is False
    assert check_structural_identity(
        "He signed a bill.",
        '<ref entity="Gavin Newsom">He</ref> signed.'
    ) is False


from knowledge_map.adapters.coreference import CoreferenceResolutionError

def test_resolve_coreferences_raises_on_critic_failure():
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    
    annotator_calls = 0
    def mock_annotator(messages, info):
        nonlocal annotator_calls
        annotator_calls += 1
        return ModelResponse(parts=[TextPart(content="Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> was happy.")])
        
    def mock_critic(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "is_valid": False,
                    "issues": ["Invalid entity mapping."]
                },
                tool_call_id="call_1"
            )
        ])
        
    with annotator_agent.override(model=FunctionModel(mock_annotator)), critic_agent.override(model=FunctionModel(mock_critic)):
        with pytest.raises(CoreferenceResolutionError) as exc_info:
            resolve_coreferences(
                "Gavin Newsom signed a bill. He was happy.",
                annotator_agent=annotator_agent,
                critic_agent=critic_agent,
                max_retries=2,
                raise_on_failure=True
            )
        
        err = exc_info.value
        assert err.failure_type == "critic_rejection"
        assert err.retry_count == 2
        assert err.validation_issues == ["Invalid entity mapping."]
        assert err.original_text == "Gavin Newsom signed a bill. He was happy."
        assert err.annotated_text == "Gavin Newsom signed a bill. <ref entity=\"Gavin Newsom\">He</ref> was happy."
        assert "model" in err.metadata
        assert "system_prompt" in err.metadata

def test_resolve_coreferences_raises_on_structural_failure():
    annotator_agent = get_annotator_agent(defer_check=True)
    critic_agent = get_critic_agent(defer_check=True)
    
    def mock_annotator(messages, info):
        return ModelResponse(parts=[TextPart(content="Gavin Newsom signed a bill. He happy.")])
        
    with annotator_agent.override(model=FunctionModel(mock_annotator)):
        with pytest.raises(CoreferenceResolutionError) as exc_info:
            resolve_coreferences(
                "Gavin Newsom signed a bill. He was happy.",
                annotator_agent=annotator_agent,
                critic_agent=critic_agent,
                max_retries=1,
                raise_on_failure=True
            )
        
        err = exc_info.value
        assert err.failure_type == "structural_mismatch"
        assert err.retry_count == 1
        assert any("structural" in issue.lower() or "structure" in issue.lower() for issue in err.validation_issues)
        assert err.original_text == "Gavin Newsom signed a bill. He was happy."
        assert err.annotated_text == "Gavin Newsom signed a bill. He happy."

def test_pydantic_ai_coreference_adapter_health_check_success():
    annotator_agent = get_annotator_agent(defer_check=True)
    
    def mock_model(messages, info):
        return ModelResponse(parts=[TextPart(content="ok")])
        
    with annotator_agent.override(model=FunctionModel(mock_model)):
        adapter = PydanticAICoreferenceAdapter(annotator_agent=annotator_agent)
        assert adapter.health_check() is True

def test_pydantic_ai_coreference_adapter_health_check_failure():
    annotator_agent = get_annotator_agent(defer_check=True)
    
    def mock_model(messages, info):
        raise RuntimeError("LLM Connection failed")
        
    with annotator_agent.override(model=FunctionModel(mock_model)):
        adapter = PydanticAICoreferenceAdapter(annotator_agent=annotator_agent)
        assert adapter.health_check() is False






