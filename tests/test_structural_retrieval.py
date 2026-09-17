import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from neo4j import AsyncDriver
from neo4j.exceptions import Neo4jError, ServiceUnavailable
from pydantic_ai.messages import UserPromptPart
from structural_support import approved_request, entity_outputs, scripted_agents

from knowledge_map.adapters.structural import Neo4jStructuralRetriever
from knowledge_map.schemas.retrieval import FailedBranch, SuccessfulBranch


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
        ("schema_transport", "schema_filtering", "transport"),
        ("schema_output", "schema_filtering", "model_output"),
        ("schema_property", "schema_filtering", "validation"),
        ("selection_transport", "typed_selection", "transport"),
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
def test_initial_attempt_failures_are_distinct_and_safe(problem, stage, kind, caplog):
    outputs = entity_outputs()
    if problem.endswith("_transport"):
        index = {"schema": 0, "selection": 1, "wiring": 2, "binding": 3}[
            problem.split("_")[0]
        ]
        outputs[index] = httpx.ConnectError("sensitive transport detail")
    elif problem == "schema_output":
        outputs[0]["cypher"] = "sensitive unwanted Cypher"
    elif problem == "schema_property":
        outputs[0]["filter_properties"] = {"Politician": ["session"]}
    elif problem == "selection_piece":
        outputs[1]["role_ids"] = ["sensitive invented identifier"]
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
    ) == ("structural", stage, kind, 1)
    assert record.deadline_exhausted is False
    assert "sensitive" not in str(record.__dict__)


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
