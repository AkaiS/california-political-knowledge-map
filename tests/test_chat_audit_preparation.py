"""Question preparation observations saved through the chat ASGI boundary."""

import json
from contextlib import asynccontextmanager, contextmanager, redirect_stdout
from datetime import UTC, datetime
from io import StringIO

import httpx
import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage
from starlette.testclient import TestClient
from test_chat_web import events, question_request
from test_chat_web_answers import approval_request
from test_chat_web_corrections import correction_request, rejection_request
from test_query_preparation import rewriter_agent
from test_retrieval import COVERAGE, Branch, coordinator

from knowledge_map.adapters.audit import SQLiteAuditStore
from knowledge_map.cli.main import main
from knowledge_map.core.audit import AuditWriter
from knowledge_map.core.chat import ChatSession, get_chat_agent
from knowledge_map.schemas.audit import AuditStageRecord
from knowledge_map.schemas.retrieval import RetrievalBranch
from knowledge_map.web import create_app


def scripted_model(outputs, *, input_tokens, output_tokens):
    outputs = iter(outputs)

    def respond(messages, info):
        output = next(outputs)
        if isinstance(output, Exception):
            raise output
        if callable(output):
            output = output(messages)
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, output)],
            usage=RequestUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        )

    return FunctionModel(respond)


@contextmanager
def audit_chat(tmp_path, proposals, assessments):
    store = SQLiteAuditStore(tmp_path / "audit.sqlite")
    writer = AuditWriter(store)
    agent, rewriter = get_chat_agent(), rewriter_agent()
    sessions = []
    branches = {branch: Branch(branch) for branch in RetrievalBranch}

    @asynccontextmanager
    async def startup():
        await writer.initialize()
        yield None

    def session_factory(question, dependencies):
        session = ChatSession(
            question,
            chat_agent=agent,
            rewriter=rewriter,
            retrieval=coordinator(branches),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
            audit=writer,
            audit_settings={},
        )
        sessions.append(session)
        return session

    with (
        agent.override(
            model=scripted_model(assessments, input_tokens=37, output_tokens=11)
        ),
        rewriter.override(
            model=scripted_model(proposals, input_tokens=23, output_tokens=7)
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
                main(
                    [
                        "audit",
                        "show",
                        sessions[0].audit_session_id,
                        "--db",
                        str(tmp_path / "audit.sqlite"),
                    ]
                )
            trail = json.loads(output.getvalue())
            assert trail["session_id"] == sessions[0].audit_session_id
            return tuple(
                AuditStageRecord.model_validate(stage) for stage in trail["stages"]
            )

        yield client, read_trail, branches


def test_proposal_and_allowed_assessment_retain_their_own_timing_and_model_usage(
    tmp_path,
):
    question = "Which organizations supported AB 1?"
    before = datetime.now(UTC)
    with audit_chat(
        tmp_path,
        [{"question": question, "relational": True}],
        [{"status": "allowed"}],
    ) as (client, read_trail, branches):
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        records = read_trail()

    assert any(event["type"] == "tool-approval-request" for event in prepared)
    assert [record.name for record in records] == [
        "session_start",
        "query_rewrite",
        "question_assessment",
    ]
    start, proposal, assessment = records
    assert len({record.session_id for record in records}) == 1
    assert len({record.stage_id for record in records}) == 3
    assert all(record.status == "succeeded" for record in records)
    assert before <= start.started_at <= proposal.started_at < proposal.ended_at
    assert proposal.ended_at <= assessment.started_at < assessment.ended_at
    assert proposal.metadata == {
        "attempt": 1,
        "question": question,
        "relational": True,
        "usage": {"requests": 1, "input_tokens": 23, "output_tokens": 7},
    }
    assert assessment.metadata == {
        "proposal_stage_id": proposal.stage_id,
        "assessment": {
            "status": "allowed",
            "explanation": None,
            "recoverable_portion": None,
        },
        "usage": {"requests": 1, "input_tokens": 37, "output_tokens": 11},
    }
    assert all(branch.requests == [] for branch in branches.values())


def test_approval_identifies_the_deferred_query_rewrite_used_by_retrieval(tmp_path):
    question = "How did legislators vote on AB 1?"
    assessment = {
        "status": "deferred",
        "explanation": "Complete roll calls are unavailable.",
        "recoverable_portion": "Reporting can identify some votes.",
    }
    with audit_chat(
        tmp_path,
        [{"question": question, "relational": True}],
        [assessment, {"introduction": "Consult the reporting."}],
    ) as (client, read_trail, branches):
        prepared = events(
            client.post("/api/chat", json=question_request("Who voted yes?"))
        )
        answered = events(client.post("/api/chat", json=approval_request(prepared)))
        records = read_trail()

    assert "Complete roll calls are unavailable." in "".join(
        event["delta"] for event in answered if event["type"] == "text-delta"
    )
    assert [record.name for record in records[:4]] == [
        "session_start",
        "query_rewrite",
        "question_assessment",
        "query_approval",
    ]
    _, proposal, assessed, approved = records[:4]
    assert assessed.metadata["assessment"] == assessment
    assert approved.status == "succeeded"
    assert approved.metadata == {
        "proposal_stage_id": proposal.stage_id,
        "question": question,
        "relational": True,
        "assessment": assessment,
    }
    assert all("attempt" not in record.metadata for record in (assessed, approved))
    for branch in branches.values():
        request, _ = branch.requests[0]
        assert request.rewrite.model_dump(mode="json") == {
            "question": question,
            "relational": True,
            "assessment": assessment,
        }


def test_declined_question_retains_the_proposal_and_assessment_without_an_answer(
    tmp_path,
):
    question = "Why did the governor privately support AB 1?"
    assessment = {
        "status": "declined",
        "explanation": "Private motives cannot be established from reporting.",
        "recoverable_portion": "Reporting can identify the stated position.",
    }
    with audit_chat(
        tmp_path, [{"question": question, "relational": True}], [assessment]
    ) as (client, read_trail, branches):
        response = client.post("/api/chat", json=question_request(question))
        completed = events(response)
        records = read_trail()

    assert assessment["explanation"] in response.text
    assert not any(event["type"] == "tool-approval-request" for event in completed)
    assert [record.name for record in records] == [
        "session_start",
        "query_rewrite",
        "question_assessment",
    ]
    assert records[-1].metadata["assessment"] == assessment
    assert all(branch.requests == [] for branch in branches.values())


def test_unavailable_rewrite_records_a_safe_failure_without_assessment_or_answer(
    tmp_path,
):
    with audit_chat(tmp_path, [httpx.ConnectError("PRIVATE_PROVIDER_BODY")], []) as (
        client,
        read_trail,
        branches,
    ):
        response = client.post("/api/chat", json=question_request("Who backed AB 1?"))
        completed = events(response)
        records = read_trail()

    assert "temporary network problem" in response.text
    assert not any(event["type"] == "tool-approval-request" for event in completed)
    assert [record.name for record in records] == ["session_start", "query_rewrite"]
    failed = records[-1]
    assert failed.status == "failed"
    assert failed.started_at < failed.ended_at
    assert failed.metadata["attempt"] == 1
    assert failed.metadata["failure_kind"] == "transport"
    assert failed.metadata["diagnostic"] == "The Query Rewriter request failed."
    assert "PRIVATE_PROVIDER_BODY" not in failed.model_dump_json() + response.text
    assert all(branch.requests == [] for branch in branches.values())


@pytest.mark.parametrize("stage", ["query_rewrite", "question_assessment"])
def test_invalid_model_output_is_recorded_only_at_the_failing_preparation_stage(
    tmp_path,
    stage,
):
    failure = UnexpectedModelBehavior("PRIVATE_MODEL_OUTPUT")
    proposals = (
        [failure]
        if stage == "query_rewrite"
        else [{"question": "Who supported AB 1?", "relational": True}]
    )
    with audit_chat(tmp_path, proposals, [failure]) as (client, read_trail, branches):
        response = client.post("/api/chat", json=question_request("Who backed AB 1?"))
        records = read_trail()

    assert "This question could not be completed." in response.text
    assert [record.name for record in records] == (
        ["session_start", "query_rewrite"]
        if stage == "query_rewrite"
        else ["session_start", "query_rewrite", "question_assessment"]
    )
    assert records[-1].status == "failed"
    assert records[-1].metadata["failure_kind"] == "model_response"
    assert "PRIVATE_MODEL_OUTPUT" not in records[-1].model_dump_json() + response.text
    assert all(branch.requests == [] for branch in branches.values())


def test_correction_connects_numbered_proposals_to_the_approved_rewrite(
    tmp_path,
):
    first = "Which organizations supported AB 1?"
    second = "Which labor unions opposed AB 1?"
    correction = "I meant labor unions that opposed it."

    def revise(messages):
        request = json.loads(messages[-1].parts[-1].content)
        assert request["original_question"] == "Who backed AB 1?"
        assert request["rejections"] == [
            {
                "question": first,
                "relational": True,
                "outcome": "rewrite_rejected",
                "correction": correction,
            }
        ]
        return {"question": second, "relational": True}

    with audit_chat(
        tmp_path,
        [{"question": first, "relational": True}, revise],
        [{"status": "allowed"}, {"status": "allowed"}, {"introduction": "Read on."}],
    ) as (client, read_trail, branches):
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        events(client.post("/api/chat", json=rejection_request(prepared)))
        rejected_trail = read_trail()
        assert [record.name for record in rejected_trail] == [
            "session_start",
            "query_rewrite",
            "question_assessment",
        ]
        assert all(branch.requests == [] for branch in branches.values())
        assert (
            client.post("/api/chat", json=approval_request(prepared)).status_code == 409
        )
        revised = events(
            client.post("/api/chat", json=correction_request(prepared, correction))
        )
        assert any(event["type"] == "tool-approval-request" for event in revised)
        events(client.post("/api/chat", json=approval_request(revised)))
        records = read_trail()

    assert [record.name for record in records[:7]] == [
        "session_start",
        "query_rewrite",
        "question_assessment",
        "query_correction",
        "query_rewrite",
        "question_assessment",
        "query_approval",
    ]
    _, proposal, _, corrected, revised_proposal, _, approved = records[:7]
    assert [proposal.metadata["attempt"], revised_proposal.metadata["attempt"]] == [
        1,
        2,
    ]
    assert corrected.metadata == {
        "proposal_stage_id": proposal.stage_id,
        "correction": correction,
    }
    assert approved.metadata["proposal_stage_id"] == revised_proposal.stage_id
    assert approved.metadata["question"] == second
    assert revised_proposal.metadata["usage"] == {
        "requests": 1,
        "input_tokens": 23,
        "output_tokens": 7,
    }
    assert len({record.session_id for record in records}) == 1
    assert len({record.stage_id for record in records}) == len(records)
    assert all(
        "attempt" not in record.metadata
        for record in records
        if record.name != "query_rewrite"
    )
    for branch in branches.values():
        assert [request.rewrite.question for request, _ in branch.requests] == [second]
