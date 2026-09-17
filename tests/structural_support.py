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
        attempt = 0

        async def respond(messages, info):
            nonlocal attempt
            if stalled_stage == index:
                await asyncio.Event().wait()
            if inspect:
                inspect(index, messages, info)
            output = outputs[index]
            if isinstance(output, list):
                output = output[min(attempt, len(output) - 1)]
            attempt += 1
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


def influence_outputs(hops=2, funder="California Leads"):
    labels = ["Organization", "Campaign", "Politician", "Bill"][: hops + 1]
    predicates = ["FUNDED", "CAMPAIGN_FOR", "DECLARED_STANCE"][:hops]
    return [
        {
            "labels": labels,
            "relationships": predicates,
            "filter_properties": {"Organization": ["name"]},
        },
        {
            "role_ids": [f"ROLE__{label.upper()}" for label in labels],
            "relationship_ids": [
                f"REL__{labels[i].upper()}__{predicate}__{labels[i + 1].upper()}"
                for i, predicate in enumerate(predicates)
            ],
            "filter_ids": ["FILTER__ORGANIZATION__NAME__EQ"],
        },
        {
            "triples": [
                {
                    "relationship_index": i,
                    "source_role_index": i,
                    "target_role_index": i + 1,
                }
                for i in range(hops)
            ],
            "filters": [{"filter_index": 0, "role_index": 0}],
        },
        {"values": [funder]},
    ]


def multi_bill_outputs():
    return [
        {
            "labels": ["Organization", "Bill"],
            "relationships": ["LOBBIED_FOR", "LOBBIED_AGAINST"],
            "filter_properties": {"Bill": ["name"]},
        },
        {
            "role_ids": ["ROLE__BILL", "ROLE__ORGANIZATION", "ROLE__BILL"],
            "relationship_ids": [
                "REL__ORGANIZATION__LOBBIED_FOR__BILL",
                "REL__ORGANIZATION__LOBBIED_AGAINST__BILL",
            ],
            "filter_ids": ["FILTER__BILL__NAME__EQ", "FILTER__BILL__NAME__EQ"],
        },
        {
            "triples": [
                {
                    "relationship_index": 0,
                    "source_role_index": 1,
                    "target_role_index": 0,
                },
                {
                    "relationship_index": 1,
                    "source_role_index": 1,
                    "target_role_index": 2,
                },
            ],
            "filters": [
                {"filter_index": 0, "role_index": 0},
                {"filter_index": 1, "role_index": 2},
            ],
        },
        {
            "values": [None, None],
            "bill_names": [
                {"slot_index": 1, "value": "Senate Bill 01947"},
                {"slot_index": 0, "value": "Assembly Bill 00186"},
            ],
        },
    ]
