"""Retrieval observations inspected through chat and the audit CLI."""

import asyncio
import json
from contextlib import asynccontextmanager, contextmanager, redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from neo4j import AsyncDriver
from neo4j.exceptions import ServiceUnavailable
from starlette.testclient import TestClient
from structural_support import entity_outputs
from test_chat_audit_preparation import scripted_model
from test_chat_web import events, question_request
from test_chat_web_answers import approval_request
from test_dense_retrieval import driver_for as dense_driver
from test_dense_retrieval import embedder_for, online_index
from test_full_text_retrieval import online_indexes
from test_query_preparation import rewriter_agent
from test_retrieval import COVERAGE, Branch, candidate, coordinator, rewrite
from test_structural_retrieval import driver_for as structural_driver

from knowledge_map.adapters.audit import SQLiteAuditStore
from knowledge_map.adapters.dense import Neo4jDenseRetriever
from knowledge_map.adapters.full_text import Neo4jFullTextRetriever
from knowledge_map.adapters.structural import (
    Neo4jStructuralRetriever,
    get_structural_agents,
)
from knowledge_map.cli.main import main
from knowledge_map.core.audit import AuditWriter
from knowledge_map.core.chat import ChatSession, get_chat_agent
from knowledge_map.schemas.audit import AuditStageRecord
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.retrieval import (
    EvidenceAssemblyFailure,
    FailedBranch,
    RetrievalBranch,
)
from knowledge_map.web import create_app


@contextmanager
def retrieval_chat(tmp_path, branches, *, relational=True, **configuration):
    path = tmp_path / "audit.sqlite"
    writer = AuditWriter(SQLiteAuditStore(path))
    agent, rewriter = get_chat_agent(), rewriter_agent()
    sessions, guidance_inputs = [], []

    def guidance(messages):
        guidance_inputs.append(json.loads(messages[-1].parts[-1].content))
        return {"introduction": "Consult the reporting."}

    @asynccontextmanager
    async def startup():
        await writer.initialize()
        yield None

    def session_factory(question, dependencies):
        session = ChatSession(
            question,
            chat_agent=agent,
            rewriter=rewriter,
            retrieval=coordinator(branches, **configuration),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
            audit=writer,
            audit_settings={},
        )
        sessions.append(session)
        return session

    with (
        agent.override(
            model=scripted_model(
                [{"status": "allowed"}, guidance], input_tokens=17, output_tokens=5
            )
        ),
        rewriter.override(
            model=scripted_model(
                [
                    {
                        "question": "Which organizations supported AB 1?",
                        "relational": relational,
                    }
                ],
                input_tokens=11,
                output_tokens=3,
            )
        ),
        TestClient(
            create_app(startup=startup, session_factory=session_factory),
            base_url="http://localhost",
        ) as client,
    ):

        def read_trail():
            assert client.portal is not None
            client.portal.call(writer.wait_for_writes)
            output = StringIO()
            with redirect_stdout(output):
                main(["audit", "show", sessions[0].audit_session_id, "--db", str(path)])
            return tuple(
                AuditStageRecord.model_validate(stage)
                for stage in json.loads(output.getvalue())["stages"]
            )

        yield client, read_trail, guidance_inputs


def answer_question(client):
    prepared = events(
        client.post("/api/chat", json=question_request("Who backed AB 1?"))
    )
    response = client.post("/api/chat", json=approval_request(prepared))
    assert events(response)[-1] == {"type": "finish", "finishReason": "stop"}
    return response


@pytest.mark.parametrize(
    "completion_order", [tuple(RetrievalBranch), tuple(reversed(RetrievalBranch))]
)
def test_concurrent_branches_retain_their_own_times_counts_and_search_terms(
    tmp_path, completion_order
):
    started, finished, release = {}, {}, {}
    ready = asyncio.Event()

    class ConcurrentBranch(Branch):
        async def retrieve(self, request, **kwargs):
            started[self.branch] = datetime.now(UTC)
            release[self.branch] = asyncio.Event()
            if len(started) == 3:
                ready.set()
                release[completion_order[0]].set()
            await ready.wait()
            await release[self.branch].wait()
            result = await super().retrieve(request, **kwargs)
            finished[self.branch] = datetime.now(UTC)
            position = completion_order.index(self.branch)
            if position < 2:
                release[completion_order[position + 1]].set()
            return result

    branches = {branch: ConcurrentBranch(branch) for branch in RetrievalBranch}
    with retrieval_chat(tmp_path, branches) as (client, read_trail, guidance_inputs):
        response = answer_question(client)
        records = read_trail()

    assert "Consult the reporting." in response.text
    searches = {
        record.name: record for record in records if record.name.endswith("_search")
    }
    assert set(searches) == {"full_text_search", "dense_search", "structural_search"}
    assert len({record.session_id for record in records}) == 1
    assert len({record.stage_id for record in records}) == len(records)
    assert max(started.values()) <= min(finished.values())
    for branch in RetrievalBranch:
        record = searches[f"{branch.value}_search"]
        assert (
            record.started_at <= started[branch] <= finished[branch] <= record.ended_at
        )
        assert record.status == "succeeded"
        assert record.metadata == {
            "returned_candidate_count": 1,
            **(
                {"search_terms": ["organizations", "supported", "ab", "1"]}
                if branch == RetrievalBranch.FULL_TEXT
                else {}
            ),
        }
    assert {
        item["branch"]: item["candidate_count"]
        for item in guidance_inputs[0]["branches"]
    } == {
        "full_text": 1,
        "dense": 1,
        "structural": 1,
    }


def test_fusion_records_distinct_eligible_ids_after_branch_limits_and_the_actual_fused_order(
    tmp_path,
):
    candidates = {
        RetrievalBranch.FULL_TEXT: [
            ("z", 1),
            ("z", 2),
            ("shared", 3),
            ("cut-full-text", 4),
        ],
        RetrievalBranch.DENSE: [("shared", 1), ("dense", 2), ("cut-dense", 3)],
        RetrievalBranch.STRUCTURAL: [
            ("graph", 1),
            ("shared", 2),
            ("cut-structural", 3),
        ],
    }
    branches = {
        branch: Branch(
            branch, tuple(candidate(branch, chunk, rank) for chunk, rank in rows)
        )
        for branch, rows in candidates.items()
    }
    with retrieval_chat(
        tmp_path,
        branches,
        fusion_config=FusionConfig(
            rank_constant=0,
            full_text_candidate_limit=2,
            dense_candidate_limit=2,
            structural_candidate_limit=2,
            fused_candidate_limit=3,
        ),
    ) as (client, read_trail, guidance_inputs):
        answer_question(client)
        records = read_trail()

    (fusion,) = (record for record in records if record.name == "fusion")
    assert fusion.status == "succeeded"
    assert fusion.metadata == {
        "eligible_by_branch": {
            "full_text": {"count": 2, "chunk_ids": ["z", "shared"]},
            "dense": {"count": 2, "chunk_ids": ["shared", "dense"]},
            "structural": {"count": 2, "chunk_ids": ["graph", "shared"]},
        },
        "fused_chunk_ids": ["shared", "graph", "z"],
    }
    assert {
        record.name: record.metadata["returned_candidate_count"]
        for record in records
        if record.name.endswith("_search")
    } == {
        "full_text_search": 4,
        "dense_search": 3,
        "structural_search": 3,
    }
    selected = sorted(
        (
            passage["candidate"]
            for source in guidance_inputs[0]["sources"]
            for passage in source["passages"]
        ),
        key=lambda item: item["rank"],
    )
    assert [item["chunk_id"] for item in selected] == ["shared", "graph", "z"]
    assert (
        max(record.ended_at for record in records if record.name.endswith("_search"))
        <= fusion.started_at
        <= fusion.ended_at
    )
    assert not any("cut-" in record.model_dump_json() for record in records)


@pytest.mark.parametrize("failure", ["exception", "returned", "deadline"])
def test_failed_branch_and_successful_empty_branch_remain_distinct_with_sibling_evidence(
    tmp_path, failure
):
    class FailingBranch(Branch):
        async def retrieve(self, request, **kwargs):
            if failure == "returned":
                return FailedBranch(branch=self.branch)
            if failure == "deadline":
                raise TimeoutError("PRIVATE_DATABASE_DIAGNOSTIC")
            raise RuntimeError("PRIVATE_DATABASE_DIAGNOSTIC")

    branches = {
        RetrievalBranch.FULL_TEXT: FailingBranch(RetrievalBranch.FULL_TEXT),
        RetrievalBranch.DENSE: Branch(RetrievalBranch.DENSE, ()),
        RetrievalBranch.STRUCTURAL: Branch(RetrievalBranch.STRUCTURAL),
    }
    with retrieval_chat(tmp_path, branches) as (client, read_trail, guidance_inputs):
        response = answer_question(client)
        records = read_trail()

    searches = {
        record.name: record for record in records if record.name.endswith("_search")
    }
    failed = searches["full_text_search"]
    assert failed.status == "failed"
    assert failed.metadata["returned_candidate_count"] == 0
    assert failed.metadata["failure_kind"] == (
        "deadline_exhausted" if failure == "deadline" else "unexpected"
    )
    assert failed.metadata["diagnostic"]
    empty = searches["dense_search"]
    assert empty.status == "succeeded"
    assert empty.metadata == {"returned_candidate_count": 0}
    assert searches["structural_search"].status == "succeeded"
    (fusion,) = (record for record in records if record.name == "fusion")
    assert fusion.metadata == {
        "eligible_by_branch": {
            "full_text": {"count": 0, "chunk_ids": []},
            "dense": {"count": 0, "chunk_ids": []},
            "structural": {"count": 1, "chunk_ids": ["structural"]},
        },
        "fused_chunk_ids": ["structural"],
    }
    assert [
        source["passages"][0]["candidate"]["chunk_id"]
        for source in guidance_inputs[0]["sources"]
    ] == ["structural"]
    assert "Full-text retrieval could not be completed." in response.text
    assert "PRIVATE_DATABASE_DIAGNOSTIC" not in response.text + "".join(
        record.model_dump_json() for record in records
    )


def test_non_relational_empty_retrieval_records_the_skipped_structural_branch(tmp_path):
    branches = {branch: Branch(branch, ()) for branch in RetrievalBranch}
    with retrieval_chat(tmp_path, branches, relational=False) as (
        client,
        read_trail,
        guidance_inputs,
    ):
        response = answer_question(client)
        records = read_trail()

    searches = {
        record.name: record for record in records if record.name.endswith("_search")
    }
    skipped = searches["structural_search"]
    assert skipped.status == "skipped"
    assert skipped.metadata == {
        "reason": "non_relational",
        "returned_candidate_count": 0,
    }
    assert branches[RetrievalBranch.STRUCTURAL].requests == []
    assert all(
        searches[name].status == "succeeded"
        for name in ("full_text_search", "dense_search")
    )
    (fusion,) = (record for record in records if record.name == "fusion")
    assert fusion.metadata == {
        "eligible_by_branch": {
            "full_text": {"count": 0, "chunk_ids": []},
            "dense": {"count": 0, "chunk_ids": []},
            "structural": {"count": 0, "chunk_ids": []},
        },
        "fused_chunk_ids": [],
    }
    assert guidance_inputs[0]["sources"] == []
    assert "Consult the reporting." in response.text


def test_cancelled_branch_still_records_zero_returned_candidates(tmp_path):
    store = SQLiteAuditStore(tmp_path / "audit.sqlite")
    writer = AuditWriter(store)

    async def run():
        await writer.initialize()
        started = asyncio.Event()

        class PausedBranch(Branch):
            async def retrieve(self, request, **kwargs):
                started.set()
                await asyncio.Event().wait()

        branches = {
            RetrievalBranch.FULL_TEXT: PausedBranch(RetrievalBranch.FULL_TEXT),
            RetrievalBranch.DENSE: Branch(RetrievalBranch.DENSE),
            RetrievalBranch.STRUCTURAL: Branch(RetrievalBranch.STRUCTURAL),
        }
        task = asyncio.create_task(
            coordinator(branches).run(
                rewrite(),
                coverage=COVERAGE,
                relevant_collection_ids=("reporting",),
                audit=writer,
                audit_session_id="cancelled",
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await writer.wait_for_writes()

    asyncio.run(run())
    records = store.read_trail("cancelled")
    (failed,) = (record for record in records if record.name == "full_text_search")
    assert failed.status == "failed"
    assert failed.metadata["returned_candidate_count"] == 0
    assert failed.metadata["failure_kind"] == "cancelled"
    assert failed.metadata["search_terms"]


def test_deadline_before_fusion_records_the_failed_stage(tmp_path):
    store = SQLiteAuditStore(tmp_path / "audit.sqlite")
    writer = AuditWriter(store)
    times = iter([0.0] * 5)

    async def run():
        await writer.initialize()
        result = await coordinator(
            deadline_seconds=1,
            clock=lambda: next(times, 1.0),
        ).run(
            rewrite(),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
            audit=writer,
            audit_session_id="expired",
        )
        await writer.wait_for_writes()
        return result

    result = asyncio.run(run())
    assert isinstance(result, EvidenceAssemblyFailure)
    assert all(
        outcome.status == "succeeded" for outcome in result.execution.outcomes[:2]
    )
    records = store.read_trail("expired")
    (fusion,) = (record for record in records if record.name == "fusion")
    assert fusion.status == "failed"
    assert fusion.metadata == {
        "failure_kind": "deadline_exhausted",
        "diagnostic": "The retrieval deadline expired before fusion.",
    }
    assert (
        max(record.ended_at for record in records if record.name.endswith("_search"))
        <= fusion.started_at
    )


@pytest.mark.parametrize("index_state", ["ONLINE", "POPULATING", None])
def test_checked_indexes_and_safe_failures_are_retained_from_concrete_retrievers(
    tmp_path, index_state
):
    text_indexes = online_indexes()
    vector_indexes = [online_index()]
    for index in [*text_indexes, *vector_indexes]:
        index["state"] = index_state
    if index_state is None:
        text_indexes, vector_indexes = [], []
    text_driver = MagicMock(spec=AsyncDriver)
    indexes, empty = AsyncMock(), AsyncMock()
    indexes.data.return_value = text_indexes
    empty.data.return_value = []
    text_driver.session.return_value.__aenter__.return_value.run = AsyncMock(
        side_effect=[indexes, empty, empty, empty]
    )
    graph_driver = structural_driver()
    graph_driver.session.return_value.__aenter__.return_value.run.side_effect = (
        ServiceUnavailable("PRIVATE_DATABASE_DIAGNOSTIC")
    )
    models = [
        scripted_model([output], input_tokens=13, output_tokens=5)
        for output in entity_outputs()
    ]
    branches = {
        RetrievalBranch.FULL_TEXT: Neo4jFullTextRetriever(text_driver),
        RetrievalBranch.DENSE: Neo4jDenseRetriever(
            dense_driver(indexes=vector_indexes), embedder_for(), candidate_limit=50
        ),
        RetrievalBranch.STRUCTURAL: Neo4jStructuralRetriever(
            graph_driver,
            agents=get_structural_agents(
                ontology_model=models[0],
                selection_model=models[1],
                wiring_model=models[2],
                binding_model=models[3],
            ),
        ),
    }
    with retrieval_chat(tmp_path, branches) as (client, read_trail, guidance_inputs):
        response = answer_question(client)
        records = read_trail()

    searches = {
        record.name: record for record in records if record.name.endswith("_search")
    }
    for branch, names, index_type in [
        (
            "full_text",
            [
                "entity_name_fulltext_index",
                "article_title_fulltext_index",
                "chunk_text_fulltext_index",
            ],
            "FULLTEXT",
        ),
        ("dense", ["chunk_vector_index"], "VECTOR"),
    ]:
        record = searches[f"{branch}_search"]
        assert record.metadata["indexes"] == [
            {
                "name": name,
                "state": index_state,
                "type": index_type if index_state else None,
            }
            for name in names
        ]
        assert record.metadata["returned_candidate_count"] == 0
        assert record.status == ("succeeded" if index_state == "ONLINE" else "failed")
        if index_state != "ONLINE":
            assert record.metadata["failure_kind"] == "index_unavailable"
            assert record.metadata["failure_stage"] == "index"
    structural = searches["structural_search"]
    assert searches["dense_search"].metadata["usage"] == {
        "requests": 1,
        "input_tokens": 8,
        "output_tokens": 0,
    }
    assert structural.status == "failed"
    assert structural.metadata == {
        "returned_candidate_count": 0,
        "failure_kind": "database",
        "failure_stage": "cypher_execution",
        "diagnostic": "Structural retrieval could not complete this stage.",
        "usage": {"requests": 4, "input_tokens": 52, "output_tokens": 20},
    }
    assert guidance_inputs[0]["sources"] == []
    (fusion,) = (record for record in records if record.name == "fusion")
    assert fusion.metadata["fused_chunk_ids"] == []
    assert "PRIVATE_DATABASE_DIAGNOSTIC" not in response.text + "".join(
        record.model_dump_json() for record in records
    )
