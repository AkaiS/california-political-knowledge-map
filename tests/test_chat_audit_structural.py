"""Structural construction results saved through chat and inspected by the CLI."""

import asyncio

import httpx
import pytest
from neo4j.exceptions import ServiceUnavailable
from structural_support import relationship_outputs
from test_chat_audit_preparation import scripted_model
from test_chat_audit_retrieval import answer_question, retrieval_chat
from test_retrieval import Branch, load_grounding
from test_structural_retrieval import driver_for

from knowledge_map.adapters.structural import (
    Neo4jStructuralRetriever,
    get_structural_agents,
)
from knowledge_map.schemas.retrieval import GroundingEvidence, RetrievalBranch

GRAPH_ROW = {
    "chunk_id": "graph-chunk",
    "source_article_id": "https://example.com/graph",
    "entry_id": "union",
    "element_id": "node:union",
    "text": "The union lobbied for AB 1.",
    "title": "Lobbying report",
    "url": "https://example.com/graph",
    "published_date": None,
    "claims": [
        {
            "source_id": "union",
            "source_element_id": "node:union",
            "target_id": "ab-1",
            "target_element_id": "node:ab-1",
            "relationship_type": "LOBBIED_FOR",
            "claim_properties": {"chunks": ["graph-chunk"]},
        }
    ],
}


def structural_branches(outputs=None, *, driver=None):
    outputs = outputs or relationship_outputs(value="AB 1")
    models = [
        scripted_model(
            output if isinstance(output, list) else [output] * 3,
            input_tokens=13,
            output_tokens=5,
        )
        for output in outputs
    ]
    return {
        RetrievalBranch.FULL_TEXT: Branch(RetrievalBranch.FULL_TEXT),
        RetrievalBranch.DENSE: Branch(RetrievalBranch.DENSE),
        RetrievalBranch.STRUCTURAL: Neo4jStructuralRetriever(
            driver or driver_for(),
            agents=get_structural_agents(
                ontology_model=models[0],
                selection_model=models[1],
                wiring_model=models[2],
                binding_model=models[3],
            ),
        ),
    }


def test_schema_filtering_saves_the_validated_ontology_selection_and_usage(tmp_path):
    with retrieval_chat(tmp_path, structural_branches()) as (client, read_trail, _):
        answer_question(client)
        records = read_trail()

    (selection,) = (
        record for record in records if record.name == "structural_schema_filtering"
    )
    assert selection.status == "succeeded"
    assert selection.metadata == {
        "selection": {
            "labels": ["Organization", "Bill"],
            "relationships": ["LOBBIED_FOR"],
            "filter_properties": {"Bill": ["name"]},
        },
        "usage": {"requests": 1, "input_tokens": 13, "output_tokens": 5},
    }
    (branch,) = (record for record in records if record.name == "structural_search")
    assert (
        branch.started_at
        <= selection.started_at
        <= selection.ended_at
        <= branch.ended_at
    )
    assert len({record.session_id for record in records}) == 1
    assert len({record.stage_id for record in records}) == len(records)


def test_typed_selection_saves_ordered_piece_occurrences_and_usage(tmp_path):
    with retrieval_chat(tmp_path, structural_branches()) as (client, read_trail, _):
        answer_question(client)
        records = read_trail()

    (selection,) = (
        record for record in records if record.name == "structural_typed_selection"
    )
    assert selection.status == "succeeded"
    assert selection.metadata == {
        "selection": {
            "role_ids": ["ROLE__ORGANIZATION", "ROLE__BILL"],
            "relationship_ids": ["REL__ORGANIZATION__LOBBIED_FOR__BILL"],
            "filter_ids": ["FILTER__BILL__NAME__EQ"],
        },
        "usage": {"requests": 1, "input_tokens": 13, "output_tokens": 5},
    }


def test_wiring_saves_the_validated_role_and_filter_assignments(tmp_path):
    with retrieval_chat(tmp_path, structural_branches()) as (client, read_trail, _):
        answer_question(client)
        records = read_trail()

    (wiring,) = (record for record in records if record.name == "structural_wiring")
    assert wiring.status == "succeeded"
    assert wiring.metadata == {
        "wiring": {
            "triples": [
                {
                    "relationship_index": 0,
                    "source_role_index": 0,
                    "target_role_index": 1,
                }
            ],
            "filters": [{"filter_index": 0, "role_index": 1}],
            "distinct_roles": [],
        },
        "usage": {"requests": 1, "input_tokens": 13, "output_tokens": 5},
    }


def test_binding_saves_accepted_values_and_model_usage(tmp_path):
    with retrieval_chat(tmp_path, structural_branches()) as (client, read_trail, _):
        answer_question(client)
        records = read_trail()

    (binding,) = (record for record in records if record.name == "structural_binding")
    assert binding.status == "succeeded"
    assert binding.metadata == {
        "bindings": {"values": ["AB 1"], "bill_names": []},
        "usage": {"requests": 1, "input_tokens": 13, "output_tokens": 5},
    }


def test_validation_saves_the_query_and_normalized_values_sent_to_neo4j(tmp_path):
    driver = driver_for()
    outputs = relationship_outputs(value="Assembly Bill 0001")
    with retrieval_chat(tmp_path, structural_branches(outputs, driver=driver)) as (
        client,
        read_trail,
        _,
    ):
        answer_question(client)
        records = read_trail()

    (validation,) = (
        record for record in records if record.name == "structural_validation"
    )
    assert validation.status == "succeeded"
    query = driver.session.return_value.__aenter__.return_value.run.call_args
    assert validation.metadata == {
        "query": query.args[0].text,
        "parameters": query.kwargs["parameters"],
    }
    assert ":LOBBIED_FOR" in validation.metadata["query"]
    assert list(validation.metadata["parameters"].values()) == ["AB 1"]
    (binding,) = (record for record in records if record.name == "structural_binding")
    assert (
        binding.started_at
        <= validation.started_at
        <= validation.ended_at
        <= binding.ended_at
    )


def test_execution_records_the_database_and_returned_row_count_without_rows(tmp_path):
    with retrieval_chat(tmp_path, structural_branches()) as (client, read_trail, _):
        answer_question(client)
        records = read_trail()

    (execution,) = (
        record for record in records if record.name == "structural_cypher_execution"
    )
    assert execution.status == "succeeded"
    assert execution.metadata == {"database": "neo4j", "returned_row_count": 0}


@pytest.mark.parametrize("rows", [[], [GRAPH_ROW]])
def test_hydration_records_candidate_count_and_keeps_grounding_in_the_answer(
    tmp_path, rows
):
    async def grounding(candidate):
        if candidate.chunk_id == "graph-chunk":
            return GroundingEvidence(
                chunk_id="graph-chunk",
                text="The union lobbied for AB 1.",
                citation={
                    "source_article_id": "https://example.com/graph",
                    "title": "Lobbying report",
                    "url": "https://example.com/graph",
                },
            )
        return await load_grounding(candidate)

    with retrieval_chat(
        tmp_path, structural_branches(driver=driver_for(rows)), load_grounding=grounding
    ) as (client, read_trail, guidance):
        response = answer_question(client)
        records = read_trail()

    (hydration,) = (
        record for record in records if record.name == "structural_hydration"
    )
    assert hydration.status == "succeeded"
    assert hydration.metadata == {"candidate_count": len(rows)}
    stages = [record for record in records if record.name.startswith("structural_")]
    assert {record.name for record in stages} == {
        "structural_search",
        "structural_schema_filtering",
        "structural_typed_selection",
        "structural_wiring",
        "structural_binding",
        "structural_validation",
        "structural_cypher_execution",
        "structural_hydration",
    }
    (branch,) = (record for record in stages if record.name == "structural_search")
    assert branch.metadata["returned_candidate_count"] == len(rows)
    assert branch.metadata["usage"] == {
        "requests": 4,
        "input_tokens": 52,
        "output_tokens": 20,
    }
    assert all(
        branch.started_at <= record.started_at <= record.ended_at <= branch.ended_at
        for record in stages
    )
    assert all("attempt" not in record.metadata for record in stages)
    assert "The union lobbied for AB 1." not in "".join(
        record.model_dump_json() for record in stages
    )
    if rows:
        assert "The union lobbied for AB 1." in response.text
        assert (
            guidance[0]["sources"][0]["passages"][0]["candidate"]["chunk_id"]
            == "graph-chunk"
        )


@pytest.mark.parametrize(
    "failure,failed_stage,kind",
    [
        ("schema_transport", "schema_filtering", "transport"),
        ("selection_output", "typed_selection", "validation"),
        ("hop_bound", "typed_selection", "hop_bound_exhausted"),
        ("wiring_output", "wiring", "validation"),
        ("binding_transport", "binding", "transport"),
        ("binding_output", "binding", "model_output"),
        ("binding_validation", "validation", "validation"),
        ("database", "cypher_execution", "database"),
        ("hydration", "hydration", "hydration"),
        ("unexpected", "cypher_execution", "unexpected"),
    ],
)
def test_structural_failures_save_the_stopped_step_and_preserve_sibling_evidence(
    tmp_path, failure, failed_stage, kind
):
    outputs = relationship_outputs(value="AB 1")
    driver = driver_for([{}] if failure == "hydration" else [])
    if failure == "schema_transport":
        outputs[0] = httpx.ConnectError("PRIVATE_PROVIDER_DETAIL")
    elif failure == "selection_output":
        outputs[1]["role_ids"] = ["PRIVATE_MODEL_OUTPUT"]
    elif failure == "hop_bound":
        outputs[1]["relationship_ids"] = ["PRIVATE_MODEL_OUTPUT"] * 4
    elif failure == "wiring_output":
        outputs[2]["filters"][0]["role_index"] = 99
    elif failure == "binding_transport":
        outputs[3] = httpx.ConnectError("PRIVATE_PROVIDER_DETAIL")
    elif failure == "binding_output":
        outputs[3] = {"raw": "PRIVATE_MODEL_OUTPUT"}
    elif failure == "binding_validation":
        outputs[3]["values"] = ["PRIVATE_MODEL_OUTPUT"]
    elif failure in {"database", "unexpected"}:
        driver.session.return_value.__aenter__.return_value.run.side_effect = (
            ServiceUnavailable("PRIVATE_DATABASE_DETAIL")
            if failure == "database"
            else RuntimeError("PRIVATE_DATABASE_DETAIL")
        )
    with retrieval_chat(tmp_path, structural_branches(outputs, driver=driver)) as (
        client,
        read_trail,
        guidance,
    ):
        response = answer_question(client)
        records = read_trail()

    (failed,) = (
        record for record in records if record.name == f"structural_{failed_stage}"
    )
    assert failed.status == "failed"
    assert failed.metadata["failure_kind"] == kind
    assert failed.metadata["failure_stage"] == failed_stage
    assert (
        failed.metadata["diagnostic"]
        == "Structural retrieval could not complete this stage."
    )
    assert "PRIVATE_" not in response.text + "".join(
        record.model_dump_json() for record in records
    )
    assert (
        "Graph connections matching the question could not be searched."
        in response.text
    )
    assert {
        source["passages"][0]["candidate"]["chunk_id"]
        for source in guidance[0]["sources"]
    } == {"full_text", "dense"}
    assert all(
        record.status == "succeeded"
        for record in records
        if record.name in {"full_text_search", "dense_search"}
    )
    if failed_stage != "hydration":
        assert not any(record.name == "structural_hydration" for record in records)
    if failure in {"selection_output", "hop_bound", "wiring_output", "binding_output"}:
        assert failed.metadata["usage"] == {
            "requests": 3,
            "input_tokens": 39,
            "output_tokens": 15,
        }
    if failure == "binding_validation":
        (binding,) = (
            record for record in records if record.name == "structural_binding"
        )
        assert binding.status == "failed"
        assert binding.metadata["usage"] == {
            "requests": 3,
            "input_tokens": 39,
            "output_tokens": 15,
        }
        assert "bindings" not in binding.metadata


def test_corrected_binding_retains_only_the_accepted_values_and_compilation(tmp_path):
    outputs = relationship_outputs(value="AB 1")
    outputs[3] = [{"values": ["PRIVATE_REJECTED_VALUE"]}, {"values": ["AB 1"]}]
    with retrieval_chat(tmp_path, structural_branches(outputs)) as (
        client,
        read_trail,
        _,
    ):
        answer_question(client)
        records = read_trail()

    (binding,) = (record for record in records if record.name == "structural_binding")
    assert binding.status == "succeeded"
    assert binding.metadata == {
        "bindings": {"values": ["AB 1"], "bill_names": []},
        "usage": {"requests": 2, "input_tokens": 26, "output_tokens": 10},
    }
    (validation,) = (
        record for record in records if record.name == "structural_validation"
    )
    assert validation.status == "succeeded"
    assert (
        binding.started_at
        <= validation.started_at
        <= validation.ended_at
        <= binding.ended_at
    )
    assert list(validation.metadata["parameters"].values()) == ["AB 1"]
    assert "PRIVATE_REJECTED_VALUE" not in "".join(
        record.model_dump_json() for record in records
    )


def test_database_deadline_records_the_active_structural_step(tmp_path):
    driver = driver_for()

    async def blocked_query(*args, **kwargs):
        await asyncio.Event().wait()

    driver.session.return_value.__aenter__.return_value.run.side_effect = blocked_query
    with retrieval_chat(
        tmp_path, structural_branches(driver=driver), deadline_seconds=0.5
    ) as (client, read_trail, _):
        answer_question(client)
        records = read_trail()

    (execution,) = (
        record for record in records if record.name == "structural_cypher_execution"
    )
    assert execution.status == "failed"
    assert execution.metadata == {
        "database": "neo4j",
        "failure_stage": "cypher_execution",
        "failure_kind": "deadline_exhausted",
        "diagnostic": "Structural retrieval could not complete this stage.",
    }
    assert all(
        record.status == "succeeded"
        for record in records
        if record.name in {"full_text_search", "dense_search"}
    )
