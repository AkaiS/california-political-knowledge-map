import pytest
from pydantic import ValidationError
from extraction import Node, Relationship, ExtractionResult

def test_node_validation_valid():
    node = Node(name="Gavin Newsom", label="PoliticalActor", properties={"role": "Governor"})
    assert node.name == "Gavin Newsom"
    assert node.label == "PoliticalActor"
    assert node.properties == {"role": "Governor"}

def test_node_validation_invalid_empty():
    with pytest.raises(ValidationError):
        Node(name="   ", label="PoliticalActor")
    with pytest.raises(ValidationError):
        Node(name="Gavin Newsom", label=" ")

def test_relationship_validation_valid():
    rel = Relationship(
        source="Gavin Newsom",
        target="Democratic Party",
        type="member_of",
        properties={"since": "2000"}
    )
    assert rel.source == "Gavin Newsom"
    assert rel.target == "Democratic Party"
    assert rel.type == "MEMBER_OF"  # uppercase normalization
    assert rel.properties == {"since": "2000"}

def test_relationship_validation_invalid_empty():
    with pytest.raises(ValidationError):
        Relationship(source=" ", target="Democratic Party", type="MEMBER_OF")
    with pytest.raises(ValidationError):
        Relationship(source="Gavin Newsom", target=" ", type="MEMBER_OF")
    with pytest.raises(ValidationError):
        Relationship(source="Gavin Newsom", target="Democratic Party", type=" ")

def test_extraction_result_valid():
    node1 = Node(name="Gavin Newsom", label="PoliticalActor")
    node2 = Node(name="Democratic Party", label="Organization")
    rel = Relationship(source="Gavin Newsom", target="Democratic Party", type="MEMBER_OF")
    res = ExtractionResult(nodes=[node1, node2], relationships=[rel])
    assert len(res.nodes) == 2
    assert len(res.relationships) == 1

def test_extraction_result_invalid_relationship_source():
    node1 = Node(name="Democratic Party", label="Organization")
    rel = Relationship(source="Gavin Newsom", target="Democratic Party", type="MEMBER_OF")
    with pytest.raises(ValidationError) as exc_info:
        ExtractionResult(nodes=[node1], relationships=[rel])
    assert "Relationship source 'Gavin Newsom' not found in defined nodes" in str(exc_info.value)

def test_extraction_result_invalid_relationship_target():
    node1 = Node(name="Gavin Newsom", label="PoliticalActor")
    rel = Relationship(source="Gavin Newsom", target="Democratic Party", type="MEMBER_OF")
    with pytest.raises(ValidationError) as exc_info:
        ExtractionResult(nodes=[node1], relationships=[rel])
    assert "Relationship target 'Democratic Party' not found in defined nodes" in str(exc_info.value)

from unittest.mock import patch
from extraction import load_instructions, get_extraction_agent

def test_load_instructions(tmp_path):
    prompt_file = tmp_path / "extraction_prompt.txt"
    prompt_content = "Please extract entities and relationships carefully."
    prompt_file.write_text(prompt_content)
    
    with patch("extraction.PROMPT_PATH", str(prompt_file)):
        instructions = load_instructions()
        assert instructions == prompt_content

def test_get_extraction_agent():
    with patch("extraction.load_instructions", return_value="Custom test prompt"):
        agent = get_extraction_agent(defer_check=True)
        assert agent.output_type == ExtractionResult
        assert "Custom test prompt" in agent._instructions

from pydantic_ai import ModelResponse, ToolCallPart, UnexpectedModelBehavior
from pydantic_ai.models.function import FunctionModel
from extraction import extract_entities

def test_extract_entities_success():
    def mock_model(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "nodes": [
                        {"name": "Gavin Newsom", "label": "PoliticalActor"},
                        {"name": "Democratic Party", "label": "Organization"}
                    ],
                    "relationships": [
                        {"source": "Gavin Newsom", "target": "Democratic Party", "type": "MEMBER_OF"}
                    ]
                },
                tool_call_id="call_1"
            )
        ])
    
    agent = get_extraction_agent(defer_check=True)
    with agent.override(model=FunctionModel(mock_model)):
        result = extract_entities("Some text", agent=agent)
        assert len(result.nodes) == 2
        assert result.nodes[0].name == "Gavin Newsom"
        assert result.nodes[1].name == "Democratic Party"
        assert len(result.relationships) == 1
        assert result.relationships[0].source == "Gavin Newsom"

def test_extract_entities_validation_failure():
    def mock_invalid_model(messages, info):
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "nodes": [
                        {"name": "Gavin Newsom", "label": "PoliticalActor"}
                    ],
                    "relationships": [
                        {"source": "Gavin Newsom", "target": "Democratic Party", "type": "MEMBER_OF"}
                    ]
                },
                tool_call_id="call_2"
            )
        ])
    
    agent = get_extraction_agent(defer_check=True)
    with agent.override(model=FunctionModel(mock_invalid_model)):
        with pytest.raises(UnexpectedModelBehavior):
            extract_entities("Some text", agent=agent)




