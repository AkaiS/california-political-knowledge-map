from unittest.mock import patch

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from knowledge_map.adapters.extraction import (
    PydanticAIEntityExtractionAdapter,
    extract_entities,
    get_extraction_agent,
    load_instructions,
)
from knowledge_map.ontology import news
from knowledge_map.schemas import ExtractionResult, Node, Relationship


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

def test_node_validation_invalid_characters():
    with pytest.raises(ValidationError) as exc_info:
        Node(name="Gavin Newsom", label="Political-Actor")
    assert "Invalid character in node label" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        Node(name="Gavin Newsom", label="Political Actor")
    assert "Invalid character in node label" in str(exc_info.value)

def test_relationship_validation_valid():
    rel = Relationship(
        source="Gavin Newsom",
        target="Democratic Party",
        relationship_type="member_of",
        properties={"since": "2000"}
    )
    assert rel.source == "Gavin Newsom"
    assert rel.target == "Democratic Party"
    assert rel.relationship_type == "MEMBER_OF"  # uppercase normalization
    assert rel.properties == {"since": "2000"}

def test_relationship_validation_invalid_empty():
    with pytest.raises(ValidationError):
        Relationship(source=" ", target="Democratic Party", relationship_type="MEMBER_OF")
    with pytest.raises(ValidationError):
        Relationship(source="Gavin Newsom", target=" ", relationship_type="MEMBER_OF")
    with pytest.raises(ValidationError):
        Relationship(source="Gavin Newsom", target="Democratic Party", relationship_type=" ")

def test_relationship_validation_invalid_characters():
    with pytest.raises(ValidationError) as exc_info:
        Relationship(source="Gavin Newsom", target="Democratic Party", relationship_type="MEMBER-OF")
    assert "Invalid character in relationship type" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        Relationship(source="Gavin Newsom", target="Democratic Party", relationship_type="MEMBER OF")
    assert "Invalid character in relationship type" in str(exc_info.value)

def test_extraction_result_valid():
    node1 = Node(name="Gavin Newsom", label="PoliticalActor")
    node2 = Node(name="Democratic Party", label="Organization")
    rel = Relationship(source="Gavin Newsom", target="Democratic Party", relationship_type="MEMBER_OF")
    res = ExtractionResult(nodes=[node1, node2], relationships=[rel])
    assert len(res.nodes) == 2
    assert len(res.relationships) == 1

def test_extraction_result_allows_dangling_relationship_source_for_adapter_conformance():
    node1 = Node(name="Democratic Party", label="Organization")
    rel = Relationship(source="Gavin Newsom", target="Democratic Party", relationship_type="MEMBER_OF")
    result = ExtractionResult(nodes=[node1], relationships=[rel])
    assert result.relationships == [rel]

def test_extraction_result_allows_dangling_relationship_target_for_adapter_conformance():
    node1 = Node(name="Gavin Newsom", label="PoliticalActor")
    rel = Relationship(source="Gavin Newsom", target="Democratic Party", relationship_type="MEMBER_OF")
    result = ExtractionResult(nodes=[node1], relationships=[rel])
    assert result.relationships == [rel]


def test_load_instructions(tmp_path):
    prompt_file = tmp_path / "extraction_prompt.txt"
    prompt_content = "Please extract carefully.\n\n{{NEWS_ONTOLOGY}}"
    prompt_file.write_text(prompt_content)
    
    with patch("knowledge_map.adapters.extraction.PROMPT_PATH", str(prompt_file)):
        instructions = load_instructions()
        assert "Please extract carefully." in instructions
        assert "{{NEWS_ONTOLOGY}}" not in instructions
        assert "`Politician`" in instructions

def test_get_extraction_agent():
    with patch("knowledge_map.adapters.extraction.load_instructions", return_value="Custom test prompt"):
        agent = get_extraction_agent(defer_check=True)
        assert agent.output_type == ExtractionResult
        assert "Custom test prompt" in agent._instructions

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
                        {"source": "Gavin Newsom", "target": "Democratic Party", "relationship_type": "MEMBER_OF"}
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

def test_extract_entities_preserves_untrusted_dangling_relationship_for_adapter():
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
                        {"source": "Gavin Newsom", "target": "Democratic Party", "relationship_type": "MEMBER_OF"}
                    ]
                },
                tool_call_id="call_2"
            )
        ])
    
    agent = get_extraction_agent(defer_check=True)
    with agent.override(model=FunctionModel(mock_invalid_model)):
        result = extract_entities("Some text", agent=agent)
        assert result.relationships[0].target == "Democratic Party"

def test_pydantic_ai_entity_extraction_adapter_success():
    received_prompt = {}

    def mock_model(messages, info):
        received_prompt["messages"] = str(messages)
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args={
                    "nodes": [
                        {"name": "Gavin Newsom", "label": "Politician"}
                    ],
                    "relationships": []
                },
                tool_call_id="call_3"
            )
        ])
        
    agent = get_extraction_agent(defer_check=True)
    with agent.override(model=FunctionModel(mock_model)):
        adapter = PydanticAIEntityExtractionAdapter(agent=agent)
        result = adapter.extract("Some text")
        assert len(result.nodes) == 1
        assert result.nodes[0].name == "Gavin Newsom"
        assert len(result.relationships) == 0
        for label in news.LABELS - {"NewsArticle", "Chunk"}:
            assert f"`{label}`" in received_prompt["messages"]
        assert "`aging-and-long-term-care`: Aging & Long-Term Care" in received_prompt["messages"]


def test_adapter_drops_undeclared_relationship_properties_into_their_own_category():
    response = {
        "nodes": [
            {"name": "Big PAC", "label": "Organization", "sub_labels": ["PAC"]},
            {"name": "Yes on 12", "label": "Campaign", "sub_labels": ["BallotMeasureCampaign"]},
        ],
        "relationships": [
            {
                "source": "Big PAC",
                "target": "Yes on 12",
                "relationship_type": "FUNDED",
                "properties": {"amount": "$6 million", "mood": "enthusiastic"},
            },
        ],
    }

    def scripted_model(messages, info):
        return ModelResponse(parts=[ToolCallPart(
            tool_name=info.output_tools[0].name,
            args=response,
            tool_call_id="scripted",
        )])

    agent = get_extraction_agent(defer_check=True)
    with agent.override(model=FunctionModel(scripted_model)):
        adapter = PydanticAIEntityExtractionAdapter(agent=agent)
        result = adapter.extract("chunk one")

    assert [rel.properties for rel in result.relationships] == [{"amount": "$6 million"}]
    report = adapter.adherence_report
    assert report["rejected_relationship_property_names"]["mood"]["count"] == 1
    assert report["rejected_relationship_property_names"]["mood"]["example_chunk_id"].startswith("sha256:")
    assert report["rejected_property_names"] == {}


def test_adapter_conforms_scripted_model_output_and_accumulates_adherence(caplog):
    responses = [
        {
            "nodes": [
                {"name": "Alex Lee", "label": "Politician", "properties": {"first_name": "Alex", "nickname": "Al"}},
                {"name": "AB 1", "label": "Bill", "properties": {"number": "AB 1"}},
                {"name": "Vote on AB 1", "label": "LegislativeEvent"},
                {"name": "Good Vote", "label": "LegislativeEvent", "sub_labels": ["Vote"]},
                {"name": "Coalition", "label": "Organization"},
                {"name": "Bad Org", "label": "Organization", "sub_labels": ["Club"]},
                {"name": "Race", "label": "Campaign"},
                {"name": "Mystery", "label": "PoliticalActor"},
            ],
            "relationships": [
                {"source": "Good Vote", "target": "AB 1", "relationship_type": "ACTION_ON"},
                {"source": "AB 1", "target": "Alex Lee", "relationship_type": "ACTION_ON"},
                {"source": "Alex Lee", "target": "Mystery", "relationship_type": "KNOWS"},
                {"source": "Alex Lee", "target": "Vote on AB 1", "relationship_type": "VOTED_AYE"},
            ],
        },
        {
            "nodes": [
                {"name": "Jamie", "label": "Politician", "properties": {"nickname": "J"}},
                {"name": "Race 2", "label": "Campaign"},
            ],
            "relationships": [],
        },
    ]

    def scripted_model(messages, info):
        return ModelResponse(parts=[ToolCallPart(
            tool_name=info.output_tools[0].name,
            args=responses.pop(0),
            tool_call_id="scripted",
        )])

    agent = get_extraction_agent(defer_check=True)
    with agent.override(model=FunctionModel(scripted_model)):
        adapter = PydanticAIEntityExtractionAdapter(agent=agent)
        first = adapter.extract("chunk one")
        adapter.extract("chunk two")

    assert [(node.name, node.sub_labels) for node in first.nodes] == [
        ("Alex Lee", []), ("AB 1", []), ("Good Vote", ["Vote"]), ("Coalition", [])
    ]
    assert first.nodes[0].properties == {"first_name": "Alex"}
    assert [relationship.relationship_type for relationship in first.relationships] == ["ACTION_ON"]
    report = adapter.adherence_report
    assert report["rejected_labels"]["Campaign"]["count"] == 2
    assert report["rejected_labels"]["PoliticalActor"]["count"] == 1
    assert report["rejected_labels"]["Club"]["count"] == 1
    assert report["rejected_relationship_types"]["ACTION_ON"]["count"] == 1
    assert report["rejected_relationship_types"]["KNOWS"]["count"] == 1
    assert report["rejected_relationship_types"]["VOTED_AYE"]["count"] == 1
    assert report["rejected_property_names"]["nickname"]["count"] == 2
    assert report["rejected_property_names"]["nickname"]["example_chunk_id"].startswith("sha256:")
    assert len([record for record in caplog.records if "Dropped extraction item" in record.message]) == 10

def test_pydantic_ai_entity_extraction_adapter_health_check_success():
    def mock_model(messages, info):
        return ModelResponse(parts=[TextPart(content="ok")])
        
    agent = get_extraction_agent(defer_check=True)
    with agent.override(model=FunctionModel(mock_model)):
        adapter = PydanticAIEntityExtractionAdapter(agent=agent)
        assert adapter.health_check() is True

def test_pydantic_ai_entity_extraction_adapter_health_check_failure():
    def mock_model(messages, info):
        raise RuntimeError("Extraction model call failed")
        
    agent = get_extraction_agent(defer_check=True)
    with agent.override(model=FunctionModel(mock_model)):
        adapter = PydanticAIEntityExtractionAdapter(agent=agent)
        assert adapter.health_check() is False





def test_adapter_drops_a_model_emitted_article_node_without_dead_lettering_the_chunk():
    response = {
        "nodes": [
            {"name": "A California Story", "label": "NewsArticle"},
            {"name": "A California Story #1", "label": "Chunk"},
            {"name": "Alex Lee", "label": "Politician"},
            {"name": "AB 1", "label": "Bill", "properties": {"number": "AB 1"}},
            {"name": "Good Vote", "label": "LegislativeEvent", "sub_labels": ["Vote"]},
        ],
        "relationships": [
            {"source": "Good Vote", "target": "AB 1", "relationship_type": "ACTION_ON"},
        ],
    }

    def scripted_model(messages, info):
        return ModelResponse(parts=[ToolCallPart(
            tool_name=info.output_tools[0].name,
            args=response,
            tool_call_id="scripted",
        )])

    agent = get_extraction_agent(defer_check=True)
    with agent.override(model=FunctionModel(scripted_model)):
        adapter = PydanticAIEntityExtractionAdapter(agent=agent)
        result = adapter.extract("chunk one")

    assert [node.name for node in result.nodes] == ["Alex Lee", "AB 1", "Good Vote"]
    assert [rel.relationship_type for rel in result.relationships] == ["ACTION_ON"]
    report = adapter.adherence_report
    assert report["rejected_labels"]["NewsArticle"]["count"] == 1
    assert report["rejected_labels"]["Chunk"]["count"] == 1
    assert report["rejected_labels"]["NewsArticle"]["example_chunk_id"].startswith("sha256:")


def test_the_output_contract_gives_a_required_sub_label_somewhere_to_go():
    """The ontology section demands a sub-label; the contract must hold one.

    `LegislativeEvent` and `Campaign` require exactly one sub-label, so a contract
    whose entity object has no `sub_labels` field asks the model for a value with
    nowhere to put it — and every such entity is then dropped by conformance.
    """

    instructions = load_instructions()
    contract, separator, _ = instructions.partition("## Closed ontology")

    assert separator, "the generated ontology section is missing from the prompt"
    assert '"sub_labels"' in contract


def test_entities_requiring_a_sub_label_survive_conformance_when_they_carry_one():
    response = {
        "nodes": [
            {"name": "Vote on AB 1", "label": "LegislativeEvent", "sub_labels": ["Vote"]},
            {"name": "Yes on Schools", "label": "Campaign", "sub_labels": ["BallotMeasureCampaign"]},
        ],
        "relationships": [],
    }

    def scripted_model(messages, info):
        return ModelResponse(parts=[ToolCallPart(
            tool_name=info.output_tools[0].name,
            args=response,
            tool_call_id="scripted",
        )])

    agent = get_extraction_agent(defer_check=True)
    with agent.override(model=FunctionModel(scripted_model)):
        adapter = PydanticAIEntityExtractionAdapter(agent=agent)
        result = adapter.extract("chunk one")

    assert [(node.label, node.sub_labels) for node in result.nodes] == [
        ("LegislativeEvent", ["Vote"]),
        ("Campaign", ["BallotMeasureCampaign"]),
    ]
    assert adapter.adherence_report["rejected_labels"] == {}
