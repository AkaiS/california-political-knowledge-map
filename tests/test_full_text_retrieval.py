import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from neo4j import AsyncDriver
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from knowledge_map.adapters.full_text import (
    Neo4jFullTextRetriever,
    extract_full_text_keywords,
)
from knowledge_map.schemas.query_preparation import QueryRewrite, QuestionAssessment
from knowledge_map.schemas.retrieval import FailedBranch, RetrievalRequest


def approved(question: str) -> QueryRewrite:
    return QueryRewrite(
        question=question,
        relational=False,
        assessment=QuestionAssessment(status="allowed"),
    )


def test_keywords_preserve_named_measures_dates_and_unicode_without_query_syntax():
    rewrite = approved("Which of José's AB-123 and SB 54 matched AB-123 in 2025-2026?")

    assert extract_full_text_keywords(rewrite) == (
        "josé",
        "ab",
        "123",
        "sb",
        "54",
        "matched",
        "2025",
        "2026",
    )
    assert extract_full_text_keywords(rewrite) == extract_full_text_keywords(rewrite)


@pytest.mark.parametrize("question", ["!? + - : *", "which of the"])
def test_unsearchable_rewrite_is_a_logged_preparation_failure(question, caplog):
    async def run():
        driver = MagicMock(spec=AsyncDriver)
        driver.session.side_effect = AssertionError(
            "preparation should stop before Neo4j"
        )
        return await Neo4jFullTextRetriever(driver).retrieve(
            RetrievalRequest(rewrite=approved(question)),
            deadline=asyncio.get_running_loop().time() + 1,
        )

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="full_text")
    (record,) = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "retrieval_branch_failed"
    ]
    assert (
        record.branch,
        record.stage,
        record.failure_kind,
        record.attempts_consumed,
    ) == ("full_text", "preparation", "validation", 0)
    assert record.deadline_exhausted is False


def online_indexes():
    return [
        {
            "name": "entity_name_fulltext_index",
            "type": "FULLTEXT",
            "state": "ONLINE",
            "labelsOrTypes": [
                "Bill",
                "Campaign",
                "Committee",
                "LegislativeEvent",
                "Organization",
                "PolicyArea",
                "Politician",
                "Prop",
            ],
            "properties": ["name"],
        },
        {
            "name": "article_title_fulltext_index",
            "type": "FULLTEXT",
            "state": "ONLINE",
            "labelsOrTypes": ["NewsArticle"],
            "properties": ["title"],
        },
        {
            "name": "chunk_text_fulltext_index",
            "type": "FULLTEXT",
            "state": "ONLINE",
            "labelsOrTypes": ["Chunk"],
            "properties": ["text"],
        },
    ]


@pytest.mark.parametrize(
    "problem", ["missing", "populating", "wrong_property", "wrong_label"]
)
def test_unusable_full_text_index_is_a_logged_index_failure(problem, caplog):
    indexes = online_indexes()
    if problem == "missing":
        indexes.pop()
    elif problem == "populating":
        indexes[0]["state"] = "POPULATING"
    elif problem == "wrong_property":
        indexes[0]["properties"] = ["description"]
    else:
        indexes[0]["labelsOrTypes"] = ["Politician"]

    async def run():
        driver = MagicMock(spec=AsyncDriver)
        session = driver.session.return_value.__aenter__.return_value
        result = AsyncMock()
        result.data.return_value = indexes
        session.run = AsyncMock(return_value=result)
        return await Neo4jFullTextRetriever(driver).retrieve(
            RetrievalRequest(rewrite=approved("housing")),
            deadline=asyncio.get_running_loop().time() + 1,
        )

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="full_text")
    (record,) = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.stage, record.failure_kind, record.attempts_consumed) == (
        "index",
        "index_unavailable",
        1,
    )


@pytest.mark.parametrize("stage", ["index", "execution"])
def test_database_failure_keeps_stage_and_never_logs_raw_exception(stage, caplog):
    async def run():
        driver = MagicMock(spec=AsyncDriver)
        session = driver.session.return_value.__aenter__.return_value
        result = AsyncMock()
        result.data.return_value = online_indexes()
        failure = ServiceUnavailable("secret-password and private approved wording")
        session.run = AsyncMock(
            side_effect=[result, failure] if stage == "execution" else failure
        )
        return await Neo4jFullTextRetriever(driver).retrieve(
            RetrievalRequest(rewrite=approved("housing")),
            deadline=asyncio.get_running_loop().time() + 1,
        )

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="full_text")
    (record,) = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.stage, record.failure_kind, record.attempts_consumed) == (
        stage,
        "database",
        1,
    )
    assert "secret-password" not in str(record.__dict__)
    assert "private approved wording" not in str(record.__dict__)


@pytest.mark.parametrize("expired", [True, False])
def test_one_deadline_stops_database_work_and_records_exhaustion(expired, caplog):
    async def run():
        driver = MagicMock(spec=AsyncDriver)
        if expired:
            driver.session.side_effect = AssertionError("expired work must not start")
        else:
            session = driver.session.return_value.__aenter__.return_value

            async def stalled_query(*args, **kwargs):
                await asyncio.Event().wait()

            session.run = AsyncMock(side_effect=stalled_query)
        return await asyncio.wait_for(
            Neo4jFullTextRetriever(driver).retrieve(
                RetrievalRequest(rewrite=approved("housing")),
                deadline=asyncio.get_running_loop().time() + (-1 if expired else 0.01),
            ),
            timeout=0.5,
        )

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="full_text")
    (record,) = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.stage, record.failure_kind, record.attempts_consumed) == (
        "deadline",
        "deadline_exhausted",
        0 if expired else 1,
    )
    assert record.deadline_exhausted is True


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
    ],
)
def test_server_index_and_timeout_errors_keep_their_failure_kind(
    code, stage, kind, caplog
):
    class ServerFailure(Neo4jError):
        @property
        def code(self):
            return code

    async def run():
        driver = MagicMock(spec=AsyncDriver)
        session = driver.session.return_value.__aenter__.return_value
        result = AsyncMock()
        result.data.return_value = online_indexes()
        session.run = AsyncMock(
            side_effect=[result, ServerFailure("sensitive details")]
        )
        return await Neo4jFullTextRetriever(driver).retrieve(
            RetrievalRequest(rewrite=approved("housing")),
            deadline=asyncio.get_running_loop().time() + 1,
        )

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="full_text")
    (record,) = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.stage, record.failure_kind) == (stage, kind)


def test_invalid_stored_chunk_identity_is_a_failed_search_not_unusable_evidence(caplog):
    async def run():
        driver = MagicMock(spec=AsyncDriver)
        session = driver.session.return_value.__aenter__.return_value
        indexes, malformed, empty = AsyncMock(), AsyncMock(), AsyncMock()
        indexes.data.return_value = online_indexes()
        malformed.data.return_value = [
            {
                "chunk_id": None,
                "source_article_id": "source",
                "entry_id": "actor",
                "labels": ["Politician"],
                "element_id": "node-1",
                "score": 0.5,
            }
        ]
        empty.data.return_value = []
        session.run = AsyncMock(side_effect=[indexes, malformed, empty, empty])
        return await Neo4jFullTextRetriever(driver).retrieve(
            RetrievalRequest(rewrite=approved("housing")),
            deadline=asyncio.get_running_loop().time() + 1,
        )

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(run())
    assert outcome == FailedBranch(branch="full_text")
    (record,) = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "retrieval_branch_failed"
    ]
    assert (record.stage, record.failure_kind) == ("execution", "validation")


def test_result_consumption_cannot_publish_success_after_the_deadline(monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()
        original_time = loop.time
        elapsed = 0

        def clock():
            return original_time() + elapsed

        async def late_result():
            nonlocal elapsed
            elapsed = 2
            return []

        driver = MagicMock(spec=AsyncDriver)
        session = driver.session.return_value.__aenter__.return_value
        indexes, empty, late = AsyncMock(), AsyncMock(), AsyncMock()
        indexes.data.return_value = online_indexes()
        empty.data.return_value = []
        late.data.side_effect = late_result
        session.run = AsyncMock(side_effect=[indexes, empty, empty, late])
        with monkeypatch.context() as patch:
            patch.setattr(loop, "time", clock)
            return await Neo4jFullTextRetriever(driver).retrieve(
                RetrievalRequest(rewrite=approved("housing")),
                deadline=loop.time() + 1,
            )

    assert asyncio.run(run()) == FailedBranch(branch="full_text")
