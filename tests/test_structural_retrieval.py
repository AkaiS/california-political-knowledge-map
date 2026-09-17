import asyncio
import json
import logging
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from neo4j import AsyncDriver
from neo4j.exceptions import Neo4jError, ServiceUnavailable
from pydantic_ai.messages import RetryPromptPart, UserPromptPart
from structural_support import (
    approved_request,
    entity_outputs,
    influence_outputs,
    multi_bill_outputs,
    scripted_agents,
)

from knowledge_map.adapters.structural import Neo4jStructuralRetriever
from knowledge_map.schemas.retrieval import FailedBranch, SuccessfulBranch


def test_schema_filter_correction_receives_specific_deterministic_failure():
    outputs = entity_outputs()
    rejected = deepcopy(outputs[0])
    rejected["filter_properties"] = {"Politician": ["session"]}
    outputs[0] = [rejected, outputs[0]]
    feedback = []

    def inspect(index, messages, info):
        if index == 0:
            feedback.append(
                [
                    part.content
                    for message in messages
                    for part in message.parts
                    if isinstance(part, RetryPromptPart)
                ]
            )

    async def run():
        return await Neo4jStructuralRetriever(
            driver_for(), agents=scripted_agents(outputs, inspect=inspect)
        ).retrieve(approved_request(), deadline=asyncio.get_running_loop().time() + 10)

    assert asyncio.run(run()) == SuccessfulBranch(branch="structural", candidates=())
    assert feedback == [[], ["filter properties must belong to selected labels"]]


def driver_for(rows=()):
    driver = MagicMock(spec=AsyncDriver)
    session = driver.session.return_value.__aenter__.return_value
    result = AsyncMock()
    result.data.return_value = list(rows)
    session.run = AsyncMock(return_value=result)
    return driver


@pytest.mark.parametrize(
    "problem,stage,kind",
    [
        ("ontology_transport", "schema_filtering", "transport"),
        ("ontology_output", "schema_filtering", "model_output"),
        ("ontology_property", "schema_filtering", "validation"),
        ("selection_transport", "typed_selection", "transport"),
        ("selection_too_many_roles", "typed_selection", "validation"),
        ("selection_too_many_relationships", "hop_bound", "hop_bound_exhausted"),
        ("selection_piece", "typed_selection", "validation"),
        ("wiring_transport", "wiring", "transport"),
        ("wiring_endpoint", "wiring", "validation"),
        ("binding_transport", "binding", "transport"),
        ("binding_output", "binding", "model_output"),
        ("binding_count", "validation", "validation"),
        ("bill_value", "validation", "validation"),
        ("database", "cypher_execution", "database"),
        ("hydration", "hydration", "hydration"),
    ],
)
def test_stage_failures_and_exhausted_corrections_are_distinct_and_safe(
    problem, stage, kind, caplog
):
    outputs = entity_outputs()
    if problem.endswith("_transport"):
        index = {"ontology": 0, "selection": 1, "wiring": 2, "binding": 3}[
            problem.split("_")[0]
        ]
        outputs[index] = httpx.ConnectError("sensitive transport detail")
    elif problem == "ontology_output":
        outputs[0]["cypher"] = "sensitive unwanted Cypher"
    elif problem == "ontology_property":
        outputs[0]["filter_properties"] = {"Politician": ["session"]}
    elif problem == "selection_piece":
        outputs[1]["role_ids"] = ["sensitive invented identifier"]
    elif problem == "selection_too_many_roles":
        outputs[1]["role_ids"] = ["one", "two", "three", "four", "five"]
    elif problem == "selection_too_many_relationships":
        outputs[1]["relationship_ids"] = ["one", "two", "three", "four"]
    elif problem == "wiring_endpoint":
        outputs[2]["filters"][0]["role_index"] = 9
    elif problem == "binding_output":
        outputs[3] = {"parameters": {"sensitive": "value"}}
    elif problem == "binding_count":
        outputs[3] = {"values": []}
    elif problem == "bill_value":
        outputs = entity_outputs("Bill", "sensitive unparseable name")
    driver = driver_for([{}] if problem == "hydration" else [])
    if problem == "database":
        driver.session.return_value.__aenter__.return_value.run.side_effect = (
            ServiceUnavailable("sensitive database detail")
        )

    async def run():
        return await Neo4jStructuralRetriever(
            driver, agents=scripted_agents(outputs)
        ).retrieve(approved_request(), deadline=asyncio.get_running_loop().time() + 10)

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="structural")
    (record,) = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_branch_failed"
    ]
    assert (
        record.branch,
        record.stage,
        record.failure_kind,
        record.attempts_consumed,
    ) == (
        "structural",
        stage,
        kind,
        1
        if problem.endswith("_transport") or problem in {"database", "hydration"}
        else 3,
    )
    assert record.deadline_exhausted is False
    assert "sensitive" not in str(record.__dict__)


def test_four_semantic_relationships_exhaust_hop_bound_corrections(caplog):
    outputs = influence_outputs(3)
    outputs[1]["relationship_ids"].append(outputs[1]["relationship_ids"][0])
    outputs[1]["role_ids"].append("ROLE__ORGANIZATION")
    received = []

    def inspect(index, messages, info):
        if index == 1:
            received.append(
                [
                    part.content
                    for message in messages
                    for part in message.parts
                    if isinstance(part, RetryPromptPart)
                ]
            )

    async def run():
        return await Neo4jStructuralRetriever(
            driver_for(), agents=scripted_agents(outputs, inspect=inspect)
        ).retrieve(approved_request(), deadline=asyncio.get_running_loop().time() + 10)

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(run()) == FailedBranch(branch="structural")
    (record,) = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.stage, record.failure_kind, record.attempts_consumed) == (
        "hop_bound",
        "hop_bound_exhausted",
        3,
    )
    assert received == [
        [],
        ["at most three question-semantic relationships are allowed"],
        ["at most three question-semantic relationships are allowed"] * 2,
    ]


@pytest.mark.parametrize(
    "problem", ["missing", "duplicate_slot", "broadcast", "positional", "invalid"]
)
def test_multi_bill_assignments_reject_missing_or_ambiguous_values(problem, caplog):
    outputs = multi_bill_outputs()
    binding = outputs[3]
    if problem == "missing":
        binding["bill_names"].pop()
    elif problem == "duplicate_slot":
        binding["bill_names"][0]["slot_index"] = 0
    elif problem == "broadcast":
        binding["bill_names"][0]["value"] = "Assembly Bill 186"
    elif problem == "positional":
        binding["values"] = ["AB 186", "SB 1947"]
    else:
        binding["bill_names"][0]["value"] = "the other bill"

    async def run():
        return await Neo4jStructuralRetriever(
            driver_for(), agents=scripted_agents(outputs)
        ).retrieve(
            approved_request(
                "Which organizations lobbied for AB 186 and against SB 1947?"
            ),
            deadline=asyncio.get_running_loop().time() + 10,
        )

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(run()) == FailedBranch(branch="structural")
    (record,) = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.stage, record.failure_kind, record.attempts_consumed) == (
        "validation",
        "validation",
        3,
    )


@pytest.mark.parametrize(
    "problem",
    [
        "disconnected",
        "repeated_relationship",
        "missing_relationship",
        "out_of_range",
        "self_loop",
        "distinct_out_of_range",
    ],
)
def test_wiring_rejects_disconnected_or_invalid_question_shapes(problem, caplog):
    outputs = influence_outputs(3)
    if problem == "disconnected":
        outputs[1]["relationship_ids"].pop()
        outputs[2]["triples"].pop()
    elif problem == "repeated_relationship":
        outputs[2]["triples"][1]["relationship_index"] = 0
    elif problem == "missing_relationship":
        outputs[2]["triples"].pop()
    elif problem == "out_of_range":
        outputs[2]["triples"][0]["target_role_index"] = 8
    elif problem == "self_loop":
        outputs[2]["triples"][0]["target_role_index"] = 0
    else:
        outputs[2]["distinct_roles"] = [{"left_role_index": 0, "right_role_index": 8}]

    async def run():
        return await Neo4jStructuralRetriever(
            driver_for(), agents=scripted_agents(outputs)
        ).retrieve(approved_request(), deadline=asyncio.get_running_loop().time() + 10)

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(run()) == FailedBranch(branch="structural")
    (record,) = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.stage, record.failure_kind, record.attempts_consumed) == (
        "wiring",
        "validation",
        3,
    )


@pytest.mark.parametrize(
    "boundary,attempts",
    [
        ("before", 0),
        ("schema", 1),
        ("binding", 1),
        ("database", 1),
        ("database_timeout", 1),
    ],
)
def test_deadline_exhaustion_is_a_failed_branch(boundary, attempts, caplog):
    driver = driver_for()
    if boundary == "database":

        async def stalled_query(*args, **kwargs):
            await asyncio.Event().wait()

        driver.session.return_value.__aenter__.return_value.run.side_effect = (
            stalled_query
        )
    elif boundary == "database_timeout":
        driver.session.return_value.__aenter__.return_value.run.side_effect = (
            Neo4jError._hydrate_neo4j(
                code="Neo.ClientError.Transaction.TransactionTimedOut",
                message="sensitive timeout detail",
            )
        )
    observed = []
    agents = scripted_agents(
        stalled_stage={"schema": 0, "binding": 3}.get(boundary),
        inspect=lambda *args: observed.append(args[0]),
    )

    async def run():
        return await Neo4jStructuralRetriever(driver, agents=agents).retrieve(
            approved_request(),
            deadline=asyncio.get_running_loop().time()
            + (-1 if boundary == "before" else 0.2),
        )

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="structural")
    (record,) = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_branch_failed"
    ]
    assert (
        record.stage,
        record.failure_kind,
        record.attempts_consumed,
        record.deadline_exhausted,
    ) == ("deadline", "deadline_exhausted", attempts, True)
    if boundary == "before":
        assert observed == []
        driver.session.assert_not_called()


def test_models_receive_only_approved_question_and_log_total_usage(caplog):
    request = approved_request("Find Ada Vale as approved")
    seen = []

    def inspect(index, messages, info):
        prompts = [
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        ]
        (content,) = prompts
        payload = json.loads(content)
        assert payload["question"] == request.rewrite.question
        assert "original_question" not in payload
        assert info.function_tools == []
        seen.append(index)

    async def run():
        return await Neo4jStructuralRetriever(
            driver_for(), agents=scripted_agents(inspect=inspect)
        ).retrieve(request, deadline=asyncio.get_running_loop().time() + 10)

    with caplog.at_level(logging.INFO):
        asyncio.run(run())
    assert seen == [0, 1, 2, 3]
    (usage,) = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_model_usage"
    ]
    assert usage.branch == "structural"
    assert usage.requests == 4
    assert usage.input_tokens > 0
    assert usage.output_tokens > 0


def test_database_failure_does_not_inherit_binding_correction_count(caplog):
    outputs = entity_outputs()
    outputs[3] = [{"values": []}, {"values": []}, outputs[3]]
    driver = driver_for()
    driver.session.return_value.__aenter__.return_value.run.side_effect = (
        ServiceUnavailable("unavailable")
    )

    async def run():
        return await Neo4jStructuralRetriever(
            driver, agents=scripted_agents(outputs)
        ).retrieve(approved_request(), deadline=asyncio.get_running_loop().time() + 10)

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(run()) == FailedBranch(branch="structural")
    (record,) = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.stage, record.attempts_consumed) == ("cypher_execution", 1)


def test_hydrated_grounding_preserves_stored_wording_exactly():
    driver = driver_for(
        [
            {
                "chunk_id": "chunk",
                "source_article_id": "source",
                "entry_id": "ada",
                "element_id": "element-ada",
                "text": "\n  Ada Vale spoke.\n",
                "title": "Speech",
                "url": "https://example.org/speech",
                "published_date": None,
            }
        ]
    )

    async def run():
        return await Neo4jStructuralRetriever(
            driver, agents=scripted_agents()
        ).retrieve(approved_request(), deadline=asyncio.get_running_loop().time() + 10)

    outcome = asyncio.run(run())
    assert isinstance(outcome, SuccessfulBranch)
    (candidate,) = outcome.candidates
    assert candidate.grounding is not None
    assert candidate.grounding.text == "\n  Ada Vale spoke.\n"
