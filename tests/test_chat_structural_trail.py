"""Accepted structural decisions observed through chat preparation and approval."""

import asyncio
import json

import httpx
import pytest
from neo4j.exceptions import Neo4jError, ServiceUnavailable
from pydantic_ai.models.function import FunctionModel
from starlette.testclient import TestClient
from structural_support import relationship_outputs, scripted_agents
from test_chat_retrieval_trail import branch_observations, chat_app, search_details
from test_chat_session_trail import chat_capture as chat_capture  # noqa: PLC0414
from test_chat_web import events, question_request
from test_chat_web_answers import approval_request
from test_retrieval import Branch
from test_structural_retrieval import driver_for

from knowledge_map.adapters.structural import Neo4jStructuralRetriever
from knowledge_map.schemas.retrieval import RetrievalBranch


def structural_chat(driver, outputs=None, *, agents=None):
    branches = {branch: Branch(branch, ()) for branch in RetrievalBranch}
    branches[RetrievalBranch.STRUCTURAL] = Neo4jStructuralRetriever(
        driver,
        agents=agents or scripted_agents(outputs or relationship_outputs()),
        database="political-reporting",
    )
    return chat_app(
        branches, rewritten_question="Which organizations lobbied for SB 623?"
    )


def complete_chat(driver, outputs=None):
    with TestClient(
        structural_chat(driver, outputs), base_url="http://localhost"
    ) as client:
        prepared = events(
            client.post("/api/chat", json=question_request("Who lobbied for SB 623?"))
        )
        return events(client.post("/api/chat", json=approval_request(prepared)))


def structural_spans(capture):
    return [
        span
        for span in capture.exported_spans_as_dict(parse_json_attributes=True)
        if span["name"] == "chat_session.structural_stage"
    ]


def test_relational_chat_records_accepted_construction_and_grounding(chat_capture):
    driver = driver_for(
        [
            {
                "chunk_id": "chunk-1",
                "source_article_id": "https://example.com/report",
                "entry_id": "california-leads",
                "element_id": "org-1",
                "text": "California Leads lobbied for SB 623.",
                "title": "Lobbying for SB 623",
                "url": "https://example.com/report",
                "published_date": "2025-06-01",
                "claims": [
                    {
                        "source_id": "california-leads",
                        "source_element_id": "org-1",
                        "target_id": "sb-623",
                        "target_element_id": "bill-1",
                        "relationship_type": "LOBBIED_FOR",
                        "claim_properties": {"chunks": ["chunk-1"]},
                    }
                ],
            }
        ]
    )
    completed = complete_chat(driver)
    details = search_details(completed)
    assert details["outcome"] == "retrieval_answer"
    assert details["branches"][-1]["candidates"][0]["chunk_id"] == "chunk-1"
    spans = structural_spans(chat_capture)
    stages = {span["attributes"]["stage"]: span for span in spans}
    assert set(stages) == {
        "schema_filtering",
        "typed_selection",
        "wiring",
        "binding",
        "validation",
        "cypher_execution",
        "hydration",
    }
    attrs = {stage: span["attributes"] for stage, span in stages.items()}
    assert {piece["id"] for piece in attrs["schema_filtering"]["accepted_pieces"]} == {
        "ROLE__ORGANIZATION",
        "ROLE__BILL",
        "FILTER__BILL__NAME__EQ",
        "REL__ORGANIZATION__LOBBIED_FOR__BILL",
    }
    assert [
        piece["id"] for piece in attrs["typed_selection"]["accepted_pieces"]["role"]
    ] == [
        "ROLE__ORGANIZATION",
        "ROLE__BILL",
    ]
    assert attrs["wiring"]["wiring"] == {
        "triples": [
            {"relationship_index": 0, "source_role_index": 0, "target_role_index": 1}
        ],
        "filters": [{"filter_index": 0, "role_index": 1}],
        "distinct_roles": [],
    }
    assert attrs["binding"]["bindings"] == {"values": ["SB 623"], "bill_names": []}
    execution = driver.session.return_value.__aenter__.return_value.run.call_args
    assert attrs["validation"]["validated_query"] == execution.args[0].text
    assert attrs["validation"]["bound_values"] == execution.kwargs["parameters"]
    assert "MATCH" in attrs["validation"]["validated_query"]
    assert "SB 623" not in attrs["validation"]["validated_query"]
    assert attrs["cypher_execution"]["database"] == "political-reporting"
    assert attrs["cypher_execution"]["row_count"] == 1
    assert attrs["hydration"]["candidate_count"] == 1
    branch = branch_observations(chat_capture)["structural"]
    all_spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    by_id = {span["context"]["span_id"]: span for span in all_spans}
    for span in spans:
        assert span["attributes"]["status"] == "succeeded"
        assert (
            span["attributes"]["chat_session_id"]
            == branch["attributes"]["chat_session_id"]
        )
        assert span["attributes"]["audit_schema_version"] == 1
        assert span["context"]["trace_id"] == branch["context"]["trace_id"]
        assert (
            branch["start_time"]
            <= span["start_time"]
            < span["end_time"]
            <= branch["end_time"]
        )
        ancestor = span
        while ancestor["context"]["span_id"] != branch["context"]["span_id"]:
            ancestor = by_id[ancestor["parent"]["span_id"]]
    agents = [
        span
        for span in all_spans
        if span["attributes"].get("gen_ai.agent.name", "").startswith("structural_")
        and span["attributes"].get("gen_ai.operation.name") == "invoke_agent"
    ]
    assert len(agents) == 4
    assert {
        by_id[span["parent"]["span_id"]]["attributes"]["stage"] for span in agents
    } == {
        "schema_filtering",
        "typed_selection",
        "wiring",
        "binding",
    }
    assert not {"messages", "input_tokens", "output_tokens", "retries"} & set().union(
        *(item.keys() for item in attrs.values())
    )


@pytest.mark.parametrize(
    "problem,stage,kind",
    [
        ("validation", "validation", "validation"),
        ("database", "cypher_execution", "database"),
        ("database_deadline", "cypher_execution", "deadline_exhausted"),
        ("deadline", "binding", "deadline_exhausted"),
        ("hydration", "hydration", "hydration"),
        ("unexpected", "cypher_execution", "unexpected"),
    ],
)
def test_structural_failures_identify_the_stage_that_stopped(
    chat_capture, problem, stage, kind
):
    outputs = relationship_outputs()
    driver = driver_for([{}] if problem == "hydration" else [])
    if problem == "validation":
        outputs[3] = {"values": ["sensitive invalid bill"]}
    elif problem == "deadline":
        outputs[3] = TimeoutError("sensitive deadline detail")
    elif problem in {"database", "database_deadline", "unexpected"}:
        error = {
            "database": ServiceUnavailable("sensitive database detail"),
            "database_deadline": Neo4jError._hydrate_neo4j(
                code="Neo.ClientError.Transaction.TransactionTimedOut",
                message="sensitive timeout detail",
            ),
            "unexpected": RuntimeError("sensitive unexpected detail"),
        }[problem]
        driver.session.return_value.__aenter__.return_value.run.side_effect = error
    completed = complete_chat(driver, outputs)
    assert search_details(completed)["branches"][-1]["status"] == "failed"
    spans = structural_spans(chat_capture)
    failures = [
        span["attributes"] for span in spans if span["attributes"]["stage"] == stage
    ]
    assert len(failures) == (3 if problem == "validation" else 1)
    for failure in failures:
        assert failure["status"] == "failed"
        assert failure["failure_stage"] == stage
        assert failure["failure_kind"] == kind
        assert (
            failure["diagnostic"]
            == "Structural retrieval could not complete this stage."
        )
        assert "validated_query" not in failure
        assert "bound_values" not in failure
    stage_names = {span["attributes"]["stage"] for span in spans}
    if problem in {"validation", "deadline"}:
        assert "cypher_execution" not in stage_names
        driver.session.assert_not_called()
    if stage != "hydration":
        assert "hydration" not in stage_names
    else:
        execution = next(
            span["attributes"]
            for span in spans
            if span["attributes"]["stage"] == "cypher_execution"
        )
        assert execution["status"] == "succeeded"
        assert execution["row_count"] == 1
    assert "sensitive" not in json.dumps([span["attributes"] for span in spans])


def test_corrected_binding_records_only_approved_values_and_preserves_bill_session(
    chat_capture,
):
    outputs = relationship_outputs()
    outputs[0]["filter_properties"]["Bill"].append("session")
    outputs[1]["filter_ids"].append("FILTER__BILL__SESSION__EQ")
    outputs[2]["filters"].append({"filter_index": 1, "role_index": 1})
    outputs[3] = [
        {"values": ["sensitive invalid bill", "2025-2026"]},
        {"values": ["Senate Bill 00623", "2025-2026"]},
    ]
    driver = driver_for()
    completed = complete_chat(driver, outputs)
    assert search_details(completed)["branches"][-1] == {
        "branch": "structural",
        "status": "succeeded",
        "candidates": [],
    }
    spans = structural_spans(chat_capture)
    validations = [
        span["attributes"]
        for span in spans
        if span["attributes"]["stage"] == "validation"
    ]
    assert [span["status"] for span in validations] == ["failed", "succeeded"]
    assert "validated_query" not in validations[0]
    assert "bound_values" not in validations[0]
    execution = driver.session.return_value.__aenter__.return_value.run.call_args
    assert validations[1]["validated_query"] == execution.args[0].text
    assert validations[1]["bound_values"] == execution.kwargs["parameters"]
    assert "2025-2026" in validations[1]["bound_values"].values()
    attrs = {span["attributes"]["stage"]: span["attributes"] for span in spans}
    assert "FILTER__BILL__SESSION__EQ" in {
        piece["id"] for piece in attrs["schema_filtering"]["accepted_pieces"]
    }
    assert (
        attrs["typed_selection"]["accepted_pieces"]["filter"][1]["property"]
        == "session"
    )
    assert attrs["binding"]["status"] == "succeeded"
    assert attrs["binding"]["bindings"] == {
        "values": ["Senate Bill 00623", "2025-2026"],
        "bill_names": [],
    }
    assert (
        attrs["cypher_execution"]["row_count"]
        == attrs["hydration"]["candidate_count"]
        == 0
    )
    assert "sensitive" not in json.dumps([span["attributes"] for span in spans])
    all_spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    binding_model_spans = [
        span
        for span in all_spans
        if span["attributes"].get("gen_ai.agent.name") == "structural_binder"
        and span["attributes"].get("gen_ai.operation.name") == "chat"
    ]
    assert len(binding_model_spans) == 2


@pytest.mark.parametrize(
    "index,stage,problem,kind",
    [
        (0, "schema_filtering", "transport", "transport"),
        (1, "typed_selection", "transport", "transport"),
        (2, "wiring", "transport", "transport"),
        (3, "binding", "transport", "transport"),
        (0, "schema_filtering", "invalid", "validation"),
        (1, "typed_selection", "invalid", "hop_bound_exhausted"),
        (2, "wiring", "invalid", "validation"),
        (3, "binding", "invalid", "model_output"),
    ],
)
def test_model_stage_failures_preserve_their_safe_classification(
    chat_capture, index, stage, problem, kind
):
    outputs = relationship_outputs()
    if problem == "transport":
        outputs[index] = httpx.ConnectError("sensitive provider detail")
    elif index == 0:
        outputs[0]["filter_properties"] = {"Organization": ["session"]}
    elif index == 1:
        outputs[1]["relationship_ids"] = ["sensitive invented piece"] * 4
    elif index == 2:
        outputs[2]["filters"][0]["role_index"] = 9
    else:
        outputs[3] = {"parameters": {"sensitive": "unaccepted output"}}
    completed = complete_chat(driver_for(), outputs)
    assert search_details(completed)["branches"][-1]["status"] == "failed"
    spans = structural_spans(chat_capture)
    failed = next(
        span["attributes"] for span in spans if span["attributes"]["stage"] == stage
    )
    assert failed["status"] == "failed"
    assert failed["failure_stage"] == stage
    assert failed["failure_kind"] == kind
    assert failed["diagnostic"] == "Structural retrieval could not complete this stage."
    assert (
        not {"accepted_pieces", "wiring", "bindings", "validated_query", "bound_values"}
        & failed.keys()
    )
    assert "sensitive" not in json.dumps([span["attributes"] for span in spans])


def test_shared_deadline_cancellation_is_recorded_on_the_active_model_stage(
    chat_capture, monkeypatch
):
    async def exercise():
        loop = asyncio.get_running_loop()
        real_time = loop.time

        async def expire(messages, info):
            expired = real_time() + 120
            monkeypatch.setattr(loop, "time", lambda: expired)
            await asyncio.Event().wait()

        agents = scripted_agents(relationship_outputs())
        agents.binder.model = FunctionModel(expire)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=structural_chat(driver_for(), agents=agents)
            ),
            base_url="http://localhost",
        ) as client:
            prepared = events(
                await client.post(
                    "/api/chat", json=question_request("Who lobbied for SB 623?")
                )
            )
            try:
                return events(
                    await client.post("/api/chat", json=approval_request(prepared))
                )
            finally:
                monkeypatch.setattr(loop, "time", real_time)

    completed = asyncio.run(exercise())
    assert search_details(completed)["branches"][-1]["status"] == "failed"
    spans = structural_spans(chat_capture)
    binding = next(
        span["attributes"] for span in spans if span["attributes"]["stage"] == "binding"
    )
    assert binding["status"] == "failed"
    assert binding["failure_stage"] == "binding"
    assert binding["failure_kind"] == "deadline_exhausted"
    assert {span["attributes"]["stage"] for span in spans} == {
        "schema_filtering",
        "typed_selection",
        "wiring",
        "binding",
    }
