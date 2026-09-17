"""The same Chat Agent assesses the rewrite and presents the assembled evidence."""

import asyncio
import json
import logging

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage, RunUsage
from test_query_preparation import rewrite_response, rewriter_agent
from test_retrieval import COVERAGE, Branch, coordinator, rewrite

from knowledge_map.core.chat import ChatSession, get_chat_agent
from knowledge_map.core.evidence import render_evidence_context
from knowledge_map.schemas.retrieval import (
    EvidenceAssemblyFailure,
    FailedBranch,
    RetrievalAnswer,
    RetrievalBranch,
)


def test_approved_evidence_returns_to_the_same_chat_agent_for_one_answer():
    received = []

    def respond(messages, info):
        received.append((messages, info))
        output = (
            {"status": "allowed"}
            if len(received) == 1
            else {"introduction": "The reporting describes the union's position."}
        )
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, output)],
            usage=RequestUsage(input_tokens=20, output_tokens=10),
        )

    agent = get_chat_agent()
    rewriter = rewriter_agent()
    original = "Find reporting about AB 1 and organizations please."
    session = ChatSession(
        original,
        chat_agent=agent,
        rewriter=rewriter,
        retrieval=coordinator(),
        coverage=COVERAGE,
        relevant_collection_ids=("reporting",),
    )

    async def exercise():
        with pytest.raises(ValueError):
            await session.approve()
        prepared = await session.prepare()
        assert prepared.status == "awaiting_approval"
        assert prepared.approval.question == rewrite().question
        assert "relational" not in prepared.model_dump_json()
        answer = await session.approve()
        with pytest.raises(ValueError):
            await session.approve()
        return answer

    with (
        agent.override(model=FunctionModel(respond)),
        rewriter.override(model=rewrite_response(rewrite().question, False)),
    ):
        result = asyncio.run(exercise())

    assert isinstance(result, RetrievalAnswer)
    assert len(result.evidence.sources) == 2
    assert len(received) == 2
    policy_prompts = [
        part.content
        for message in received[0][0]
        for part in message.parts
        if isinstance(part, UserPromptPart)
    ]
    assert original not in json.dumps(policy_prompts)
    final_prompts = [
        part.content
        for message in received[1][0]
        for part in message.parts
        if isinstance(part, UserPromptPart)
    ]
    assert original in final_prompts
    assert final_prompts[-1] == render_evidence_context(result.evidence)
    assert "execution" not in json.loads(final_prompts[-1])
    assert all(info.function_tools == [] for _, info in received)
    assert result.introduction == "The reporting describes the union's position."


@pytest.mark.parametrize("failed_count", [0, 1, 2, 3])
def test_final_answer_discloses_all_failed_branches_and_repeats_deferred_limit(
    failed_count,
):
    branches_in_failure_order = (
        RetrievalBranch.STRUCTURAL,
        RetrievalBranch.FULL_TEXT,
        RetrievalBranch.DENSE,
    )
    failed = branches_in_failure_order[:failed_count]

    class Failed(Branch):
        async def retrieve(self, request, **kwargs):
            return FailedBranch(branch=self.branch)

    branches = {
        branch: Failed(branch) if branch in failed else Branch(branch, ())
        for branch in RetrievalBranch
    }
    calls = []
    limit = "Complete roll calls are not available."

    def respond(messages, info):
        calls.append(messages)
        output = (
            {
                "status": "deferred",
                "explanation": limit,
                "recoverable_portion": "Reporting can identify some recorded votes.",
            }
            if len(calls) == 1
            else {"introduction": "Consult these sources."}
        )
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

    agent, rewriter = get_chat_agent(), rewriter_agent()
    session = ChatSession(
        "How did everyone vote on AB 1?",
        chat_agent=agent,
        rewriter=rewriter,
        retrieval=coordinator(branches),
        coverage=COVERAGE,
        relevant_collection_ids=("reporting",),
    )

    async def exercise():
        prepared = await session.prepare()
        assert prepared.status == "awaiting_approval"
        assert prepared.approval.explanation == limit
        return await session.approve()

    with (
        agent.override(model=FunctionModel(respond)),
        rewriter.override(model=rewrite_response(rewrite().question, True)),
    ):
        answer = asyncio.run(exercise())
    assert isinstance(answer, RetrievalAnswer)
    assert limit in answer.introduction
    assert answer.evidence.execution.request.rewrite.assessment.explanation == limit
    for disclosure in answer.evidence.failure_disclosures:
        assert disclosure in answer.introduction
    if failed_count:
        assert answer.introduction.startswith(
            "Graph connections matching the question could not be searched."
        )
        assert "No matching graph connections" not in answer.introduction
    else:
        assert (
            "No matching graph connections were found in the available graph."
            in answer.introduction
        )
    assert len(calls) == 2


def test_usage_includes_rejected_rewrites_policy_retrieval_and_answer_without_a_token_cutoff(
    caplog,
):
    chat_calls = []

    def respond(messages, info):
        chat_calls.append(messages)
        output = (
            {"status": "allowed"}
            if len(chat_calls) <= 2
            else {"introduction": "Read the reporting."}
        )
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, output)],
            usage=RequestUsage(input_tokens=1_000_000, output_tokens=20),
        )

    def rewrite_model(messages, info):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"question": rewrite().question, "relational": False},
                )
            ],
            usage=RequestUsage(input_tokens=100, output_tokens=10),
        )

    class MeteredBranch(Branch):
        async def retrieve(self, request, *, usage=None, **kwargs):
            assert usage is not None
            usage.incr(RunUsage(requests=1, input_tokens=13, output_tokens=2))
            return await super().retrieve(request, **kwargs)

    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    branches[RetrievalBranch.DENSE] = MeteredBranch(RetrievalBranch.DENSE)
    agent, rewriter = get_chat_agent(), rewriter_agent()
    session = ChatSession(
        "Show reporting",
        chat_agent=agent,
        rewriter=rewriter,
        retrieval=coordinator(branches),
        coverage=COVERAGE,
        relevant_collection_ids=("reporting",),
    )

    async def exercise():
        await session.prepare()
        rejection = session.reject("Keep AB 1 explicit.")
        assert rejection.correction == "Keep AB 1 explicit."
        await session.prepare()
        return await session.approve()

    with (
        caplog.at_level(logging.INFO),
        agent.override(model=FunctionModel(respond)),
        rewriter.override(model=FunctionModel(rewrite_model)),
    ):
        answer = asyncio.run(exercise())
    assert isinstance(answer, RetrievalAnswer)
    (record,) = [
        r for r in caplog.records if getattr(r, "event", None) == "chat_total_usage"
    ]
    assert (record.requests, record.input_tokens, record.output_tokens) == (
        6,
        3_000_213,
        82,
    )


def test_assembly_failure_discloses_branch_failures_without_requesting_an_answer():
    class Failed(Branch):
        async def retrieve(self, request, **kwargs):
            return FailedBranch(branch=self.branch)

    async def unavailable(citation):
        raise LookupError("original Story unavailable")

    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    branches[RetrievalBranch.STRUCTURAL] = Failed(RetrievalBranch.STRUCTURAL)
    requests = []

    def respond(messages, info):
        requests.append(messages)
        assert len(requests) == 1
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"status": "allowed"})]
        )

    agent, rewriter = get_chat_agent(), rewriter_agent()
    session = ChatSession(
        "Find support for AB 1",
        chat_agent=agent,
        rewriter=rewriter,
        retrieval=coordinator(branches, load_story=unavailable),
        coverage=COVERAGE,
        relevant_collection_ids=("reporting",),
    )

    async def exercise():
        await session.prepare()
        return await session.approve()

    with (
        agent.override(model=FunctionModel(respond)),
        rewriter.override(model=rewrite_response(rewrite().question, True)),
    ):
        result = asyncio.run(exercise())
    assert isinstance(result, EvidenceAssemblyFailure)
    assert result.failure_disclosures == (
        "Graph connections matching the question could not be searched.",
        "Grounding Evidence could not be assembled and verified.",
    )
    assert set(result.execution.evidence_by_branch) == {"full_text", "dense"}
    assert len(requests) == 1


@pytest.mark.parametrize("terminal", ["declined", "rewrite_unavailable"])
def test_unapproved_terminal_questions_never_start_retrieval(terminal):
    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    calls = []

    def respond(messages, info):
        calls.append(messages)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "status": "declined",
                        "explanation": "Private motives are outside question policy.",
                    },
                )
            ]
        )

    def unavailable(messages, info):
        raise httpx.ConnectError("temporary rewriter outage")

    agent, rewriter = get_chat_agent(), rewriter_agent()
    session = ChatSession(
        "Why did they privately support AB 1?",
        chat_agent=agent,
        rewriter=rewriter,
        retrieval=coordinator(branches),
        coverage=COVERAGE,
        relevant_collection_ids=("reporting",),
    )

    async def exercise():
        prepared = await session.prepare()
        assert prepared.status == terminal
        with pytest.raises(ValueError):
            await session.approve()

    with (
        agent.override(model=FunctionModel(respond)),
        rewriter.override(
            model=(
                FunctionModel(unavailable)
                if terminal == "rewrite_unavailable"
                else rewrite_response(rewrite().question, True)
            )
        ),
    ):
        asyncio.run(exercise())
    assert all(branch.requests == [] for branch in branches.values())
    assert len(calls) == (0 if terminal == "rewrite_unavailable" else 1)
