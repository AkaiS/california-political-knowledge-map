import asyncio
import json

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from knowledge_map.adapters.structural import get_structural_agents
from knowledge_map.schemas.query_preparation import QueryRewrite, QuestionAssessment
from knowledge_map.schemas.retrieval import RetrievalRequest


def approved_request(question="Find Ada Vale"):
    return RetrievalRequest(
        rewrite=QueryRewrite(
            question=question,
            relational=True,
            assessment=QuestionAssessment(status="allowed"),
        )
    )


def entity_outputs(label="Politician", value="Ada Vale", property="name"):
    return [
        {
            "labels": [label],
            "relationships": [],
            "filter_properties": {label: [property]},
        },
        {
            "role_ids": [f"ROLE__{label.upper()}"],
            "relationship_ids": [],
            "filter_ids": [f"FILTER__{label.upper()}__{property.upper()}__EQ"],
        },
        {"triples": [], "filters": [{"filter_index": 0, "role_index": 0}]},
        {"values": [value]},
    ]


def scripted_agents(outputs=None, *, inspect=None, stalled_stage=None):
    outputs = outputs or entity_outputs()

    def model_at(index):
        async def respond(messages, info):
            if stalled_stage == index:
                await asyncio.Event().wait()
            if inspect:
                inspect(index, messages, info)
            output = outputs[index]
            if isinstance(output, Exception):
                raise output
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, json.dumps(output))]
            )

        return FunctionModel(respond)

    return get_structural_agents(
        ontology_model=model_at(0),
        selection_model=model_at(1),
        wiring_model=model_at(2),
        binding_model=model_at(3),
    )


def relationship_outputs(
    source="Organization", predicate="LOBBIED_FOR", target="Bill", value="SB 623"
):
    return [
        {
            "labels": [source, target],
            "relationships": [predicate],
            "filter_properties": {target: ["name"]},
        },
        {
            "role_ids": [f"ROLE__{source.upper()}", f"ROLE__{target.upper()}"],
            "relationship_ids": [
                f"REL__{source.upper()}__{predicate}__{target.upper()}"
            ],
            "filter_ids": [f"FILTER__{target.upper()}__NAME__EQ"],
        },
        {
            "triples": [
                {
                    "relationship_index": 0,
                    "source_role_index": 0,
                    "target_role_index": 1,
                }
            ],
            "filters": [{"filter_index": 0, "role_index": 1}],
        },
        {"values": [value]},
    ]
