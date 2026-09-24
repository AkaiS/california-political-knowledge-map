"""Fusion and Evidence Assembly observations through the chat ASGI interface."""

import asyncio
import json

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from starlette.testclient import TestClient
from test_chat_preparation_trail import scripted_model
from test_chat_retrieval_trail import chat_app, search_details
from test_chat_session_trail import chat_capture as chat_capture  # noqa: PLC0414
from test_chat_web import events, no_dependencies, question_request
from test_chat_web_answers import approval_request
from test_query_preparation import rewriter_agent
from test_retrieval import COVERAGE, Branch, candidate, coordinator, load_grounding

from knowledge_map.core.chat import ChatSession, get_chat_agent
from knowledge_map.core.evidence import EvidenceHydrationError
from knowledge_map.schemas.evidence import EvidenceContextLimits
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.retrieval import (
    CoverageDescription,
    FailedBranch,
    MonthlyCoverage,
    RetrievalBranch,
)
from knowledge_map.web import create_app


def stage_spans(capture):
    return {
        span["name"]: span
        for span in capture.exported_spans_as_dict(parse_json_attributes=True)
        if span["name"] in {"chat_session.fusion", "chat_session.evidence_assembly"}
    }


def application_attributes(span):
    return {
        key: value
        for key, value in span["attributes"].items()
        if not key.startswith(("code.", "logfire.", "exception."))
    }


@pytest.mark.parametrize(
    "completion_order", [tuple(RetrievalBranch), tuple(reversed(RetrievalBranch))]
)
def test_fusion_records_actual_eligible_ids_and_order_after_duplicates_and_limits(
    chat_capture, completion_order
):
    loaded = []

    async def store(fused):
        loaded.append(fused)
        return await load_grounding(fused)

    async def exercise():
        entered = {branch: asyncio.Event() for branch in RetrievalBranch}
        release = {branch: asyncio.Event() for branch in RetrievalBranch}
        finished = {branch: asyncio.Event() for branch in RetrievalBranch}

        class ConcurrentBranch(Branch):
            async def retrieve(self, request, **kwargs):
                entered[self.branch].set()
                await release[self.branch].wait()
                result = await super().retrieve(request, **kwargs)
                finished[self.branch].set()
                return result

        rows = (
            (("shared", 4), ("outside", 3), ("shared", 1), ("text", 2)),
            (("dense", 1), ("shared", 2), ("dense-tail", 3)),
            (("structural", 1), ("shared", 2), ("structural-tail", 3)),
        )
        branches = {
            branch: ConcurrentBranch(
                branch,
                tuple(candidate(branch, chunk, rank) for chunk, rank in branch_rows),
            )
            for branch, branch_rows in zip(RetrievalBranch, rows, strict=True)
        }
        app = chat_app(
            branches,
            load_grounding=store,
            fusion_config=FusionConfig(
                full_text_candidate_limit=2,
                dense_candidate_limit=1,
                structural_candidate_limit=1,
                fused_candidate_limit=3,
            ),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            prepared = events(
                await client.post(
                    "/api/chat", json=question_request("Who backed AB 1?")
                )
            )
            approval = asyncio.create_task(
                client.post("/api/chat", json=approval_request(prepared))
            )
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(event.wait() for event in entered.values())), 2
                )
                for branch in completion_order:
                    release[branch].set()
                    await asyncio.wait_for(finished[branch].wait(), 2)
                return events(await approval)
            finally:
                for event in release.values():
                    event.set()
                await approval

    completed = asyncio.run(exercise())
    details = search_details(completed)
    assert details["outcome"] == "retrieval_answer"
    assert [len(branch["candidates"]) for branch in details["branches"]] == [4, 3, 3]
    assert [value.chunk_id for value in loaded] == ["shared", "structural", "dense"]
    fusion = stage_spans(chat_capture)["chat_session.fusion"]
    attrs = fusion["attributes"]
    assert attrs["status"] == "succeeded"
    assert attrs["eligible_branches"] == {
        "full_text": {"count": 2, "chunk_ids": ["shared", "text"]},
        "dense": {"count": 1, "chunk_ids": ["dense"]},
        "structural": {"count": 1, "chunk_ids": ["structural"]},
    }
    assert attrs["fused_chunk_ids"] == [value.chunk_id for value in loaded]
    approval = next(
        span
        for span in chat_capture.exported_spans_as_dict(parse_json_attributes=True)
        if span["name"] == "chat_session.approve"
    )
    assert attrs["chat_session_id"] == approval["attributes"]["chat_session_id"]
    assert attrs["audit_schema_version"] == 1
    assert fusion["parent"]["span_id"] == approval["context"]["span_id"]
    assert fusion["context"]["trace_id"] == approval["context"]["trace_id"]
    assert not {"rank", "scores", "routes", "contributions", "text"} & attrs.keys()
    assert "The union supports AB 1." not in json.dumps(attrs)


def evidence_chat(
    branches, *, prompts, coverage=COVERAGE, monthly_coverage=(), **options
):
    def respond(messages, info):
        prompts.append(messages[-1].parts[-1].content)
        output = (
            {"status": "allowed"}
            if len(prompts) == 1
            else {"introduction": "Read the reporting."}
        )
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

    agent = get_chat_agent()
    agent.model = FunctionModel(respond)
    rewriter = rewriter_agent()
    rewriter.model = scripted_model(
        [{"question": "Which organizations support AB 1?", "relational": False}]
    )

    def session_factory(question, dependencies):
        return ChatSession(
            question,
            chat_agent=agent,
            rewriter=rewriter,
            retrieval=coordinator(branches, **options),
            coverage=coverage,
            relevant_collection_ids=("reporting",),
            monthly_coverage=monthly_coverage,
        )

    return create_app(startup=no_dependencies, session_factory=session_factory)


def complete_chat(app):
    with TestClient(app, base_url="http://localhost") as client:
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        return events(client.post("/api/chat", json=approval_request(prepared)))


def test_assembly_records_actual_selection_omission_reasons_and_measured_context(
    chat_capture,
):
    prompts = []
    branches = {branch: Branch(branch, ()) for branch in RetrievalBranch}
    branches[RetrievalBranch.FULL_TEXT] = Branch(
        RetrievalBranch.FULL_TEXT,
        tuple(
            candidate(RetrievalBranch.FULL_TEXT, chunk, rank)
            for rank, chunk in enumerate(("large", "session-small", "tail"), 1)
        ),
    )
    loaded = []

    async def store(fused):
        loaded.append(fused.chunk_id)
        evidence = await load_grounding(fused)
        return evidence.model_copy(
            update={
                "text": "Oversized stored passage. " * 1000
                if fused.chunk_id == "large"
                else "Selected stored passage."
            }
        )

    coverage = CoverageDescription(
        entries=(
            *COVERAGE.entries,
            COVERAGE.entries[0].model_copy(update={"collection_id": "unrelated"}),
        )
    )
    months = tuple(
        MonthlyCoverage(
            collection_id=collection,
            month="2026-09",
            availability=COVERAGE.entries[0].availability,
        )
        for collection in ("unrelated", "reporting")
    )
    completed = complete_chat(
        evidence_chat(
            branches,
            prompts=prompts,
            coverage=coverage,
            monthly_coverage=months,
            load_grounding=store,
            context_limits=EvidenceContextLimits(character_limit=3000, max_passages=1),
        )
    )
    assert search_details(completed)["outcome"] == "retrieval_answer"
    assert loaded == ["large", "session-small"]
    context = json.loads(prompts[-1])
    assert [
        passage["candidate"]["chunk_id"]
        for source in context["sources"]
        for passage in source["passages"]
    ] == ["session-small"]
    assembly = stage_spans(chat_capture)["chat_session.evidence_assembly"]
    attrs = assembly["attributes"]
    assert attrs["status"] == "succeeded"
    assert attrs["selected_chunk_ids"] == ["session-small"]
    assert attrs["omitted_chunks"] == [
        {"chunk_id": "large", "reason": "character_limit"},
        {"chunk_id": "tail", "reason": "passage_limit"},
    ]
    assert attrs["coverage"] == context["coverage"] == COVERAGE.model_dump(mode="json")
    assert (
        attrs["monthly_coverage"]
        == context["monthly_coverage"]
        == [months[1].model_dump(mode="json")]
    )
    assert attrs["context"] == {
        "unit": "characters",
        "limit": 3000,
        "used": len(prompts[-1]),
        "max_passages": 1,
        "omitted_passages": 2,
    }
    assert 0 < attrs["context"]["used"] < 3000
    fusion = stage_spans(chat_capture)["chat_session.fusion"]
    assert fusion["attributes"]["fused_chunk_ids"] == ["large", "session-small", "tail"]
    assert assembly["parent"] == fusion["parent"]
    assert attrs["chat_session_id"] == fusion["attributes"]["chat_session_id"]
    assert attrs["audit_schema_version"] == 1
    assert assembly["start_time"] >= fusion["end_time"]
    recorded = json.dumps(
        [span["attributes"] for span in stage_spans(chat_capture).values()]
    )
    for excluded in (
        "Oversized stored passage.",
        "Selected stored passage.",
        "ranking",
        "routes",
        "fusion_score",
    ):
        assert excluded not in recorded


@pytest.mark.parametrize(
    "error,kind",
    [
        (EvidenceHydrationError("private storage address"), "hydration"),
        (ValueError("private mismatched passage"), "validation"),
        (TimeoutError("private storage timeout"), "deadline_exhausted"),
    ],
)
def test_assembly_failure_records_a_safe_cause_without_a_retrieval_answer(
    chat_capture, error, kind
):
    prompts = []

    async def store(fused):
        if isinstance(error, ValueError):
            evidence = await load_grounding(fused)
            return evidence.model_copy(update={"chunk_id": "private-wrong-chunk"})
        raise error

    completed = complete_chat(
        evidence_chat(None, prompts=prompts, load_grounding=store)
    )
    assert search_details(completed)["outcome"] == "assembly_failed"
    assert len(prompts) == 1
    rendered = "".join(
        event["delta"] for event in completed if event["type"] == "text-delta"
    )
    assert rendered == "Grounding Evidence could not be assembled."
    spans = stage_spans(chat_capture)
    assert spans["chat_session.fusion"]["attributes"]["status"] == "succeeded"
    failed = spans["chat_session.evidence_assembly"]["attributes"]
    assert failed["status"] == "failed"
    assert failed["failure_kind"] == kind
    assert failed["diagnostic"] == "Grounding Evidence could not be assembled."
    assert failed["limits"] == {"character_limit": 24000, "max_passages": 12}
    assert not {"selected_chunk_ids", "context"} & failed.keys()
    assert "private" not in json.dumps(
        [application_attributes(span) for span in spans.values()]
    )


@pytest.mark.parametrize("has_candidate", [False, True])
def test_zero_passage_assembly_accounts_for_empty_failed_and_skipped_branches(
    chat_capture, has_candidate
):
    prompts = []

    class UnavailableBranch(Branch):
        async def retrieve(self, request, **kwargs):
            return FailedBranch(branch=self.branch)

    branches = {branch: Branch(branch, ()) for branch in RetrievalBranch}
    branches[RetrievalBranch.DENSE] = UnavailableBranch(RetrievalBranch.DENSE)
    if has_candidate:
        branches[RetrievalBranch.FULL_TEXT] = Branch(
            RetrievalBranch.FULL_TEXT,
            (candidate(RetrievalBranch.FULL_TEXT, "2025-2026-session"),),
        )

    async def store(fused):
        evidence = await load_grounding(fused)
        return evidence.model_copy(update={"text": "Long stored passage. " * 1000})

    completed = complete_chat(
        evidence_chat(
            branches,
            prompts=prompts,
            load_grounding=store,
            context_limits=EvidenceContextLimits(character_limit=3000),
        )
    )
    details = search_details(completed)
    assert details["outcome"] == "retrieval_answer"
    assert [branch["status"] for branch in details["branches"]] == [
        "succeeded",
        "failed",
        "skipped",
    ]
    context = json.loads(prompts[-1])
    assert context["sources"] == []
    spans = stage_spans(chat_capture)
    fusion = spans["chat_session.fusion"]["attributes"]
    ids = ["2025-2026-session"] if has_candidate else []
    assert fusion["eligible_branches"] == {
        "full_text": {"count": int(has_candidate), "chunk_ids": ids},
        "dense": {"count": 0, "chunk_ids": []},
        "structural": {"count": 0, "chunk_ids": []},
    }
    assert fusion["fused_chunk_ids"] == ids
    assembly = spans["chat_session.evidence_assembly"]["attributes"]
    assert assembly["status"] == "succeeded"
    assert assembly["selected_chunk_ids"] == []
    assert assembly["omitted_chunks"] == (
        [{"chunk_id": "2025-2026-session", "reason": "character_limit"}]
        if has_candidate
        else []
    )
    assert assembly["context"]["used"] == len(prompts[-1])
    assert assembly["context"]["omitted_passages"] == int(has_candidate)
    assert "failure_kind" not in assembly


@pytest.mark.parametrize(
    "expiry", ["before_fusion", "after_hydration", "during_hydration"]
)
def test_deadline_exhaustion_is_assigned_to_the_active_selection_stage(
    chat_capture, monkeypatch, expiry
):
    async def exercise():
        now = 100.0
        finished = set()
        loop = asyncio.get_running_loop()
        real_time = loop.time

        def expire():
            nonlocal now
            now = 160.0

        class DeadlineBranch(Branch):
            async def retrieve(self, request, **kwargs):
                outcome = await super().retrieve(request, **kwargs)
                finished.add(self.branch)
                if len(finished) == 3 and expiry == "before_fusion":
                    loop.call_soon(expire)
                return outcome

        async def store(fused):
            evidence = await load_grounding(fused)
            expire()
            if expiry == "during_hydration":
                expired = real_time() + 120
                monkeypatch.setattr(loop, "time", lambda: expired)
                await asyncio.Event().wait()
            return evidence

        branches = {branch: DeadlineBranch(branch) for branch in RetrievalBranch}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=chat_app(branches, clock=lambda: now, load_grounding=store)
            ),
            base_url="http://localhost",
        ) as client:
            prepared = events(
                await client.post(
                    "/api/chat", json=question_request("Who backed AB 1?")
                )
            )
            try:
                return events(
                    await client.post("/api/chat", json=approval_request(prepared))
                )
            finally:
                monkeypatch.setattr(loop, "time", real_time)

    completed = asyncio.run(exercise())
    details = search_details(completed)
    assert details["outcome"] == "assembly_failed"
    assert all(branch["status"] == "succeeded" for branch in details["branches"])
    spans = stage_spans(chat_capture)
    stage = "fusion" if expiry == "before_fusion" else "evidence_assembly"
    attrs = spans[f"chat_session.{stage}"]["attributes"]
    assert attrs["status"] == "failed"
    assert attrs["failure_kind"] == "deadline_exhausted"
    assert attrs["diagnostic"] == (
        "Retrieval candidates could not be fused."
        if stage == "fusion"
        else "Grounding Evidence could not be assembled."
    )
    if expiry == "before_fusion":
        assert "chat_session.evidence_assembly" not in spans
        assert "fused_chunk_ids" not in attrs
    else:
        assert spans["chat_session.fusion"]["attributes"]["status"] == "succeeded"


@pytest.mark.parametrize(
    "stage,kind",
    [
        ("fusion", "validation"),
        ("fusion", "unexpected"),
        ("evidence_assembly", "unexpected"),
    ],
)
def test_raised_selection_failures_identify_the_stage_and_preserve_chat_failure(
    chat_capture, stage, kind
):
    branches = {
        branch: Branch(branch, (candidate(branch, "shared"),))
        for branch in RetrievalBranch
    }
    options = {}
    if stage == "fusion" and kind == "validation":
        branches[RetrievalBranch.DENSE] = Branch(
            RetrievalBranch.DENSE,
            (
                candidate(RetrievalBranch.DENSE, "shared").model_copy(
                    update={"source_article_id": "private-conflicting-source"}
                ),
            ),
        )
    elif stage == "fusion":
        options["fusion_config"] = FusionConfig(
            full_text_weight=1e308,
            dense_weight=1e308,
            structural_weight=1.7e308,
            rank_constant=0,
        )
    else:

        async def store(fused):
            raise RuntimeError("private unhandled storage detail")

        options["load_grounding"] = store
    completed = complete_chat(chat_app(branches, **options))
    assert any(event["type"] == "error" for event in completed)
    assert not any(
        event["type"] == "tool-output-available"
        and event.get("output", {}).get("outcome") == "retrieval_answer"
        for event in completed
    )
    spans = stage_spans(chat_capture)
    failed = spans[f"chat_session.{stage}"]["attributes"]
    assert failed["status"] == "failed"
    assert failed["failure_kind"] == kind
    assert failed["diagnostic"] == (
        "Retrieval candidates could not be fused."
        if stage == "fusion"
        else "Grounding Evidence could not be assembled."
    )
    if stage == "fusion":
        assert "chat_session.evidence_assembly" not in spans
        assert "fused_chunk_ids" not in failed
    assert "private" not in json.dumps(
        [application_attributes(span) for span in spans.values()]
    )
