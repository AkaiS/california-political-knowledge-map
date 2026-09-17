"""The Query Rewrite and approval boundary used by the Chat Agent."""

import asyncio
import json
import logging

import httpx
import pytest
from pydantic import ValidationError
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from knowledge_map.core.question_preparation import (
    QuestionPreparation,
    get_query_rewriter,
)
from knowledge_map.schemas import DeploymentKind, ModelDeployment
from knowledge_map.schemas.query_preparation import (
    QueryRewriteProposal,
    QuestionAssessment,
)


def rewriter_agent():
    return get_query_rewriter(
        ModelDeployment(
            kind=DeploymentKind.LOCAL,
            model="rewrite-test-model",
            endpoint="http://rewrite.test:8080",
        )
    )


def rewrite_response(question, relational):
    def respond(messages, info):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={"question": question, "relational": relational},
                )
            ]
        )

    return FunctionModel(respond)


@pytest.mark.parametrize(
    "values",
    [
        {"question": "", "relational": True},
        {"question": " \n ", "relational": True},
        {"question": "Who endorsed Steve Hilton?"},
        {"question": "Who endorsed Steve Hilton?", "relational": "true"},
        {"question": "Who endorsed Steve Hilton?", "relational": 1},
    ],
)
def test_rewrite_requires_a_nonblank_question_and_boolean_route(values):
    with pytest.raises(ValidationError):
        QueryRewriteProposal.model_validate(values)


def test_only_the_approved_rewrite_becomes_the_retrieval_question():
    original = (
        "Give me sources about unions and their position on AB 1018, "
        "the 2025-2026 one, with citations please."
    )
    rewritten = (
        "Which labor unions have a recorded position on AB 1018 "
        "in the 2025-2026 session?"
    )
    assessed = []

    async def assess(rewrite):
        assessed.append(rewrite)
        return QuestionAssessment(status="allowed")

    agent = rewriter_agent()
    preparation = QuestionPreparation(
        original,
        rewriter=agent,
        assess_question_policy_and_coverage=assess,
    )
    with pytest.raises(ValueError):
        preparation.approve()

    with agent.override(model=rewrite_response(rewritten, True)):
        result = asyncio.run(preparation.prepare())

    assert assessed == [QueryRewriteProposal(question=rewritten, relational=True)]
    assert result.status == "awaiting_approval"
    assert result.approval is not None
    assert result.approval.question == rewritten
    assert "relational" not in result.model_dump_json()
    approved = preparation.approve()
    assert approved.question == rewritten
    assert approved.relational is True
    assert approved.assessment.status == "allowed"
    with pytest.raises(ValueError):
        preparation.approve()


def test_declined_rewrite_stops_with_an_explanation_before_approval():
    rewritten = "Why did Gavin Newsom privately decide to support SB 9?"
    explanation = "Private motives cannot be established from the available evidence."
    assessed = []

    async def assess(rewrite):
        assessed.append(rewrite)
        return QuestionAssessment(status="declined", explanation=explanation)

    agent = rewriter_agent()
    preparation = QuestionPreparation(
        "Tell me his real reason for SB 9.",
        rewriter=agent,
        assess_question_policy_and_coverage=assess,
    )
    with agent.override(model=rewrite_response(rewritten, True)):
        result = asyncio.run(preparation.prepare())

    assert assessed == [QueryRewriteProposal(question=rewritten, relational=True)]
    assert result.status == "declined"
    assert result.message == explanation
    assert "approval" not in result.model_dump()
    with pytest.raises(ValueError):
        preparation.approve()


def test_deferred_rewrite_explains_its_limit_and_recoverable_portion_before_approval():
    rewritten = "How did every California senator vote on SB 1007 in 2025-2026?"
    explanation = "A complete roll call is unavailable."
    recoverable = "Reporting may identify individual senators' votes."

    async def assess(rewrite):
        assert rewrite == QueryRewriteProposal(question=rewritten, relational=True)
        return QuestionAssessment(
            status="deferred",
            explanation=explanation,
            recoverable_portion=recoverable,
        )

    agent = rewriter_agent()
    preparation = QuestionPreparation(
        "Every senator's SB 1007 vote in 2025-2026 with sources please.",
        rewriter=agent,
        assess_question_policy_and_coverage=assess,
    )
    with agent.override(model=rewrite_response(rewritten, True)):
        result = asyncio.run(preparation.prepare())

    assert result.status == "awaiting_approval"
    assert result.approval is not None
    assert result.approval.question == rewritten
    assert result.approval.explanation == explanation
    assert result.approval.recoverable_portion == recoverable
    assert "relational" not in result.model_dump_json()
    approved = preparation.approve()
    assert approved.assessment.status == "deferred"
    assert approved.assessment.explanation == explanation
    assert approved.assessment.recoverable_portion == recoverable


@pytest.mark.parametrize("correction", [None, "I meant AB 186 in 2025-2026."])
def test_rejection_retains_feedback_and_only_a_new_proposal_can_be_approved(
    correction, caplog
):
    original = "Who lobbied for it? Please cite sources."
    first = "Which organizations lobbied for SB 9 in the 2025-2026 session?"
    second = "Which organizations lobbied for AB 186 in the 2025-2026 session?"
    requests = []
    scripted_questions = iter([first, second])

    def respond(messages, info):
        request = messages[-1]
        assert isinstance(request, ModelRequest)
        part = request.parts[-1]
        assert isinstance(part, UserPromptPart) and isinstance(part.content, str)
        requests.append(json.loads(part.content))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={"question": next(scripted_questions), "relational": True},
                )
            ]
        )

    async def assess(rewrite):
        return QuestionAssessment(status="allowed")

    agent = rewriter_agent()
    preparation = QuestionPreparation(
        original,
        rewriter=agent,
        assess_question_policy_and_coverage=assess,
    )
    with caplog.at_level(logging.INFO), agent.override(model=FunctionModel(respond)):
        asyncio.run(preparation.prepare())
        rejected = preparation.reject(correction=correction)
        with pytest.raises(ValueError):
            preparation.approve()
        revised = asyncio.run(preparation.prepare())

    assert rejected.model_dump() == {
        "outcome": "rewrite_rejected",
        "question": first,
        "relational": True,
        "correction": correction,
    }
    assert preparation.rejections == (rejected,)
    assert requests[-1]["original_question"] == original
    assert requests[-1]["rejections"] == [rejected.model_dump()]
    assert revised.approval is not None
    assert revised.approval.question == second
    assert preparation.approve().question == second
    record = next(
        record for record in caplog.records if record.event == "rewrite_rejected"
    )
    assert (record.question, record.relational, record.correction) == (
        first,
        True,
        correction,
    )


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("offline"),
        ModelAPIError("rewrite-test-model", "offline"),
        ModelHTTPError(503, "rewrite-test-model"),
        ModelHTTPError(429, "rewrite-test-model"),
    ],
)
def test_transport_exhaustion_records_unavailable_without_an_original_question_fallback(
    failure, caplog
):
    assessed = []

    async def assess(rewrite):
        assessed.append(rewrite)
        return QuestionAssessment(status="allowed")

    def unavailable(messages, info):
        raise failure

    agent = rewriter_agent()
    preparation = QuestionPreparation(
        "Who endorsed Steve Hilton?",
        rewriter=agent,
        assess_question_policy_and_coverage=assess,
    )
    with (
        caplog.at_level(logging.WARNING),
        agent.override(model=FunctionModel(unavailable)),
    ):
        result = asyncio.run(preparation.prepare())

    assert result.status == "rewrite_unavailable"
    assert "approval" not in result.model_dump()
    assert result.message is not None
    assert "network" in result.message.lower()
    assert "temporary" in result.message.lower()
    assert assessed == []
    with pytest.raises(ValueError):
        preparation.approve()
    record = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "rewrite_unavailable"
    )
    assert record.stage == "query_rewrite"
    assert record.failure_kind == "transport"


def test_a_second_prepare_cannot_replace_a_proposal_while_it_is_being_prepared():
    question = "Which stored articles discuss housing in July 2026?"

    async def assess(rewrite):
        return QuestionAssessment(status="allowed")

    async def exercise():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def respond(messages, info):
            if not entered.is_set():
                entered.set()
                await release.wait()
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=info.output_tools[0].name,
                        args={"question": question, "relational": False},
                    )
                ]
            )

        agent = rewriter_agent()
        preparation = QuestionPreparation(
            question,
            rewriter=agent,
            assess_question_policy_and_coverage=assess,
        )
        with agent.override(model=FunctionModel(respond)):
            first = asyncio.create_task(preparation.prepare())
            await entered.wait()
            try:
                with pytest.raises(ValueError):
                    await preparation.prepare()
            finally:
                release.set()
                result = await first
            with pytest.raises(ValueError):
                await preparation.prepare()
        assert result.approval is not None
        assert result.approval.question == question
        approved = preparation.approve()
        assert approved.question == question
        assert approved.relational is False

    asyncio.run(exercise())
