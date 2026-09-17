import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from neo4j import AsyncDriver
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from knowledge_map.adapters.dense import Neo4jDenseRetriever
from knowledge_map.adapters.embedding import get_embedding_embedder
from knowledge_map.config import TransportSettings
from knowledge_map.schemas.query_preparation import QueryRewrite, QuestionAssessment
from knowledge_map.schemas.retrieval import FailedBranch, RetrievalRequest


def approved_request():
    return RetrievalRequest(
        rewrite=QueryRewrite(
            question="Which organizations supported SB 623?",
            relational=True,
            assessment=QuestionAssessment(status="allowed"),
        )
    )


def embedding_response(vectors=None):
    if vectors is None:
        vectors = [[1.0] + [0.0] * 767]
    return httpx.Response(
        200,
        json={
            "object": "list",
            "model": "embeddinggemma",
            "data": [
                {"object": "embedding", "index": i, "embedding": vector}
                for i, vector in enumerate(vectors)
            ],
            "usage": {"prompt_tokens": 8, "total_tokens": 8},
        },
    )


def embedder_for(handler=lambda request: embedding_response()):
    return get_embedding_embedder(
        transport=httpx.MockTransport(handler),
        transport_settings=TransportSettings(max_attempts=1),
    )


def online_index():
    return {
        "name": "chunk_vector_index",
        "type": "VECTOR",
        "state": "ONLINE",
        "labelsOrTypes": ["Chunk"],
        "properties": ["embedding"],
        "options": {
            "indexConfig": {
                "vector.dimensions": 768,
                "vector.similarity_function": "COSINE",
            }
        },
    }


def driver_for(indexes=None, rows=()):
    driver = MagicMock(spec=AsyncDriver)
    session = driver.session.return_value.__aenter__.return_value
    index_result, search_result = AsyncMock(), AsyncMock()
    index_result.data.return_value = [online_index()] if indexes is None else indexes
    search_result.data.return_value = list(rows)
    session.run = AsyncMock(side_effect=[index_result, search_result])
    return driver


def failure_record(caplog):
    (record,) = [
        r
        for r in caplog.records
        if getattr(r, "event", None) == "retrieval_branch_failed"
    ]
    assert record.branch == "dense"
    assert "sensitive" not in str(record.__dict__)
    return record


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "populating",
        "wrong_type",
        "wrong_label",
        "wrong_property",
        "wrong_dimension",
        "wrong_similarity",
    ],
)
def test_unusable_vector_index_is_a_logged_failure(problem, caplog):
    index = online_index()
    if problem == "populating":
        index["state"] = "POPULATING"
    elif problem == "wrong_type":
        index["type"] = "FULLTEXT"
    elif problem == "wrong_label":
        index["labelsOrTypes"] = ["NewsArticle"]
    elif problem == "wrong_property":
        index["properties"] = ["other_embedding"]
    elif problem == "wrong_dimension":
        index["options"]["indexConfig"]["vector.dimensions"] = 3
    elif problem == "wrong_similarity":
        index["options"]["indexConfig"]["vector.similarity_function"] = "euclidean"

    async def run():
        return await Neo4jDenseRetriever(
            driver_for([] if problem == "missing" else [index]),
            embedder_for(),
            candidate_limit=5,
        ).retrieve(approved_request(), deadline=asyncio.get_running_loop().time() + 1)

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="dense")
    record = failure_record(caplog)
    assert (record.stage, record.failure_kind, record.attempts_consumed) == (
        "index",
        "index_unavailable",
        1,
    )


@pytest.mark.parametrize("stage", ["index", "execution"])
def test_database_errors_keep_the_failed_stage_and_hide_raw_errors(stage, caplog):
    async def run():
        driver = driver_for()
        session = driver.session.return_value.__aenter__.return_value
        index_result = AsyncMock()
        index_result.data.return_value = [online_index()]
        error = ServiceUnavailable("sensitive credentials and question")
        session.run.side_effect = (
            [index_result, error] if stage == "execution" else error
        )
        return await Neo4jDenseRetriever(
            driver, embedder_for(), candidate_limit=5
        ).retrieve(approved_request(), deadline=asyncio.get_running_loop().time() + 1)

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="dense")
    record = failure_record(caplog)
    assert (record.stage, record.failure_kind, record.attempts_consumed) == (
        stage,
        "database",
        1,
    )


@pytest.mark.parametrize(
    "stage", ["expired", "embedding", "index", "execution", "consumption"]
)
def test_one_deadline_bounds_embedding_and_all_database_work(stage, caplog):
    async def stalled(*args, **kwargs):
        await asyncio.Event().wait()

    async def run():
        driver = driver_for()
        embedder = embedder_for(stalled) if stage == "embedding" else embedder_for()
        session = driver.session.return_value.__aenter__.return_value
        if stage == "expired":
            driver.session.side_effect = AssertionError("Expired work must not start")
        elif stage == "index":
            session.run.side_effect = stalled
        elif stage in {"execution", "consumption"}:
            index_result, stalled_result = AsyncMock(), AsyncMock()
            index_result.data.return_value = [online_index()]
            if stage == "execution":

                async def query_then_stall(*args, **kwargs):
                    if session.run.await_count == 1:
                        return index_result
                    await stalled()

                session.run.side_effect = query_then_stall
            else:
                stalled_result.data.side_effect = stalled
                session.run.side_effect = [index_result, stalled_result]
        return await asyncio.wait_for(
            Neo4jDenseRetriever(driver, embedder, candidate_limit=5).retrieve(
                approved_request(),
                deadline=asyncio.get_running_loop().time()
                + (-1 if stage == "expired" else 0.02),
            ),
            timeout=0.5,
        )

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="dense")
    record = failure_record(caplog)
    assert (
        record.stage,
        record.failure_kind,
        record.attempts_consumed,
        record.deadline_exhausted,
    ) == ("deadline", "deadline_exhausted", 0 if stage == "expired" else 1, True)


@pytest.mark.parametrize(
    "problem",
    [
        "connection",
        "provider",
        "empty",
        "multiple",
        "dimension",
        "zero",
        "invalid_number",
    ],
)
def test_embedding_failure_is_preparation_failure_and_does_not_search(problem, caplog):
    def handler(request):
        if problem == "connection":
            raise httpx.ConnectError("sensitive endpoint and request")
        if problem == "provider":
            return httpx.Response(503, json={"error": {"message": "sensitive details"}})
        vectors = {
            "empty": [],
            "multiple": [[1.0] * 768, [1.0] * 768],
            "dimension": [[1.0, 0.0]],
            "zero": [[0.0] * 768],
            "invalid_number": [[None] * 768],
        }
        return embedding_response(vectors[problem])

    async def run():
        driver = driver_for()
        driver.session.side_effect = AssertionError(
            "Invalid embeddings must not reach Neo4j"
        )
        return await Neo4jDenseRetriever(
            driver, embedder_for(handler), candidate_limit=5
        ).retrieve(approved_request(), deadline=asyncio.get_running_loop().time() + 1)

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="dense")
    record = failure_record(caplog)
    assert (record.stage, record.failure_kind, record.attempts_consumed) == (
        "preparation",
        "transport" if problem in {"connection", "provider"} else "validation",
        1,
    )


@pytest.mark.parametrize(
    "code,stage,kind",
    [
        (
            "Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration",
            "deadline",
            "deadline_exhausted",
        ),
        (
            "Neo.TransientError.Transaction.TransactionTimedOut",
            "deadline",
            "deadline_exhausted",
        ),
        ("Neo.ClientError.Schema.IndexNotFound", "index", "index_unavailable"),
        ("Neo.ClientError.Schema.IndexNotApplicable", "index", "index_unavailable"),
    ],
)
def test_server_timeout_or_lost_index_is_not_a_generic_database_failure(
    code, stage, kind, caplog
):
    class ServerFailure(Neo4jError):
        @property
        def code(self):
            return code

    async def run():
        driver = driver_for()
        session = driver.session.return_value.__aenter__.return_value
        index_result = AsyncMock()
        index_result.data.return_value = [online_index()]
        session.run.side_effect = [
            index_result,
            ServerFailure("sensitive driver details"),
        ]
        return await Neo4jDenseRetriever(
            driver, embedder_for(), candidate_limit=5
        ).retrieve(approved_request(), deadline=asyncio.get_running_loop().time() + 1)

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="dense")
    record = failure_record(caplog)
    assert (record.stage, record.failure_kind, record.attempts_consumed) == (
        stage,
        kind,
        1,
    )


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "2"])
def test_candidate_limit_must_be_a_positive_integer(limit):
    with pytest.raises(ValueError, match="candidate_limit"):
        Neo4jDenseRetriever(driver_for(), embedder_for(), candidate_limit=limit)
