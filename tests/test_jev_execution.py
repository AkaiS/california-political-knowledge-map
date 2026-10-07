"""Chat protocol and evaluations exercise the packaged Jev retrieval pipeline."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from neo4j import Driver, GraphDatabase
from starlette.testclient import TestClient
from test_chat_eval_task import run_one
from test_chat_session_trail import chat_capture as chat_capture  # noqa: PLC0414
from test_chat_startup import (
    startup_dependencies as startup_dependencies,  # noqa: PLC0414
)
from test_chat_web import events, question_request
from test_chat_web_answers import approval_request
from test_jev_staged_selector import Fake
from test_model_factory import chat_completion
from test_retrieval import Branch, candidate

from knowledge_map.adapters.jev import JevStructuralRetriever, ReadGraph
from knowledge_map.chat_startup import chat_dependencies
from knowledge_map.evaluation.tasks import chat as task_module
from knowledge_map.schemas.retrieval import RetrievalBranch
from knowledge_map.web import create_app

ARTICLE = "https://calmatters.org/invented/"
QUESTION = "Which organizations have a recorded position on AB 1?"
ROW = {
    "role_0_id": "bill-1",
    "role_0_properties": {"name": "AB 1"},
    "role_1_id": "union-1",
    "role_1_properties": {"name": "Invented Union"},
    "semantic_relationship_0_relationship": "DECLARED_STANCE",
    "semantic_relationship_0_properties": {"alignment": "POSITIVE"},
    "semantic_relationship_0_article_ids": [ARTICLE],
    "evidence_groups": [{"kind": "semantic_relationship_0", "ids": ["chunk-1"]}],
}
GROUNDING = {
    "chunk_id": "chunk-1",
    "source_article_id": ARTICLE,
    "text": "The union supports AB 1.",
    "title": "Union supports bill",
    "published_date": "2026-09-01",
}


class SyntheticJev(Fake):
    def __init__(self):
        super().__init__(
            {"SINGLE__REL__ORGANIZATION__DECLARED_STANCE__BILL"},
            properties={"property_0_FILTER__BILL__NAME__EQ"},
        )
        self.schema_calls = 0

    def system_one(self, **request):
        if "semantic_schema" not in request["state"]:
            return super().system_one(**request)
        self.schema_calls += 1
        yes = {
            "label__Bill",
            "label__Organization",
            "relationship__DECLARED_STANCE",
            "property__Bill__name",
        }
        return SimpleNamespace(
            nouls={
                key: SimpleNamespace(noul=0.99 if key in yes else 0.01)
                for key in request["questions"]
            },
            model="synthetic-jev",
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )

    def close(self):
        pass


@pytest.fixture
def jev_startup(startup_dependencies, monkeypatch):
    _, driver, _, _, _, _, _, inventory = startup_dependencies
    jev = SyntheticJev()
    monkeypatch.setattr("knowledge_map.chat_startup.jev_client", lambda: jev)
    sync_driver = MagicMock(spec=Driver)
    queries = []

    def sync_query(query, parameters=None, **kwargs):
        text = str(query)
        queries.append((text, parameters))
        result = MagicMock()
        if text.startswith("EXPLAIN"):
            result.consume.return_value = SimpleNamespace(query_type="r")
        elif "RETURN DISTINCT toString(n.id)" in text:
            result.__iter__.return_value = iter([{"id": "bill-1", "value": "AB 1"}])
        else:
            result.data.return_value = [ROW]
        return result

    sync_driver.session.return_value.__enter__.return_value.run.side_effect = sync_query
    monkeypatch.setattr(GraphDatabase, "driver", lambda *args, **kwargs: sync_driver)

    class Validator:
        def validate(self, query):
            return 1, []

    monkeypatch.setattr(
        JevStructuralRetriever,
        "_validators",
        staticmethod(lambda graph: (Validator(),) * 3),
    )

    async def async_query(query, parameters=None):
        if "available_count" in str(query):
            return inventory
        result = AsyncMock()
        if "WHERE chunk.id IN $ids" in str(query):
            result.data.return_value = [GROUNDING]
        else:
            result.data.return_value = [{**GROUNDING, "url": ARTICLE}]
        return result

    driver.session.return_value.__aenter__.return_value.run.side_effect = async_query
    branches = {}
    for name, branch in (
        ("Neo4jFullTextRetriever", RetrievalBranch.FULL_TEXT),
        ("Neo4jDenseRetriever", RetrievalBranch.DENSE),
    ):
        found = candidate(branch, "chunk-1").model_copy(
            update={"source_article_id": ARTICLE}
        )
        retriever = Branch(branch, (found,))
        branches[branch] = retriever
        monkeypatch.setattr(
            f"knowledge_map.chat_startup.{name}",
            lambda *args, retriever=retriever, **kwargs: retriever,
        )

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200)
        payload = json.loads(request.content)
        properties = (
            payload["response_format"]["json_schema"]["schema"]["properties"]
            if "response_format" in payload
            else payload["tools"][0]["function"]["parameters"]["properties"]
        )
        if "relational" in properties:
            output = {"question": QUESTION, "relational": False}
        elif "status" in properties:
            output = {"status": "allowed"}
        elif "source_notes" in properties:
            output = {"introduction": "Read the recorded position."}
        elif "triples" in properties:
            output = {
                "triples": [
                    {
                        "relationship_index": 0,
                        "source_role_index": 1,
                        "target_role_index": 0,
                    }
                ],
                "filters": [{"filter_index": 0, "role_index": 0}],
                "distinct_roles": [],
                "rationale": "Selected occurrences.",
            }
        else:
            output = {"values": ["AB 1"]}
        return httpx.Response(200, json=chat_completion(json.dumps(output)))

    original_client = httpx.AsyncClient.__bases__[0]

    class Client(original_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(respond)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", Client)

    @asynccontextmanager
    async def startup(**kwargs):
        async with chat_dependencies(**kwargs) as dependencies:
            assert isinstance(
                dependencies.retrieval._structural, JevStructuralRetriever
            )
            yield dependencies

    return startup, jev, branches, queries


def assert_jev_execution(execution, jev, branches, queries):
    assert jev.schema_calls == 1
    assert all(b.requests for b in branches.values())
    structural = execution.outcomes[-1]
    assert structural.status == "succeeded", structural
    assert structural.construction["backend"] == "jev-staged"
    assert structural.construction["binding"]["parameters"] == {"parameter_0": "AB 1"}
    assert structural.semantic_results[0]["role_1_id"] == "union-1"
    claims = structural.candidates[0].routes[0].graph_claims
    assert claims[0].relationship_type == "DECLARED_STANCE"
    assert claims[0].source.id == "union-1"
    assert claims[0].chunk_ids == ("chunk-1",)
    assert any(text.startswith("EXPLAIN MATCH") for text, _ in queries)
    assert any(
        "RETURN DISTINCT" in text and "evidence_groups" in text for text, _ in queries
    )
    assert execution.request.structural_reporting
    assert not execution.request.rewrite.relational


def test_evaluation_uses_shared_startup_and_jev_cypher_with_both_text_branches(
    jev_startup, monkeypatch, chat_capture
):
    startup, jev, branches, queries = jev_startup
    monkeypatch.setattr(task_module, "chat_dependencies", startup)
    report = run_one()
    assert not report.failures
    output = report.cases[0].output
    assert output.failure is None
    assert "The union supports AB 1." in output.rendered_text
    assert_jev_execution(output.answer.evidence.execution, jev, branches, queries)
    assert "jev_composer" in {record["component"] for record in output.messages}
    assert output.settings["retrieval_settings"]["cypher_backend"] == "jev-staged"


def test_chat_client_approval_uses_the_same_jev_execution(jev_startup, chat_capture):
    startup, jev, branches, queries = jev_startup
    sessions = []
    from knowledge_map.chat_startup import new_chat_session

    def session_factory(question, dependencies):
        session = new_chat_session(question, dependencies)
        sessions.append(session)
        return session

    with TestClient(
        create_app(startup=startup, session_factory=session_factory),
        base_url="http://localhost",
    ) as client:
        prepared = events(client.post("/api/chat", json=question_request(QUESTION)))
        assert jev.schema_calls == 0
        response = client.post(
            "/api/chat", json=approval_request(prepared, question=QUESTION)
        )
        assert response.status_code == 200
        assert "The union supports AB 1." in response.text
        assert "DECLARED_STANCE" in response.text
    assert_jev_execution(sessions[0].retrieval_result.execution, jev, branches, queries)


def test_jev_failure_retains_sparse_and_dense_evidence(
    jev_startup, monkeypatch, chat_capture
):
    startup, jev, _branches, queries = jev_startup

    def unavailable(**request):
        raise ValueError("private API diagnostic")

    jev.system_one = unavailable
    monkeypatch.setattr(task_module, "chat_dependencies", startup)
    output = run_one().cases[0].output
    assert output.failure is None
    execution = output.answer.evidence.execution
    assert [b.status for b in execution.outcomes] == [
        "succeeded",
        "succeeded",
        "failed",
    ]
    assert (
        "Graph connections matching the question could not be searched."
        in output.rendered_text
    )
    assert "The union supports AB 1." in output.rendered_text
    assert not queries
    assert "private API diagnostic" not in output.model_dump_json()


def test_read_graph_forces_database_read_routing_and_timeout():
    async def exercise():
        driver = MagicMock(spec=Driver)
        graph = ReadGraph(driver, "selected-db", asyncio.get_running_loop().time() + 5)
        graph.session(database="wrong", default_access_mode="WRITE")
        driver.session.assert_called_once_with(
            database="selected-db", default_access_mode="READ"
        )
        graph.execute_query(
            "EXPLAIN MATCH (n) RETURN n", database_="wrong", routing_="w"
        )
        args, kwargs = driver.execute_query.call_args
        assert 0 < args[0].timeout <= 5
        assert kwargs["database_"] == "selected-db"
        assert kwargs["routing_"] == "r"

    asyncio.run(exercise())
