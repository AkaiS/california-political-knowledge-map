"""End-to-end evaluation retains answers and failures as inspectable cases."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import yaml
from pydantic_ai import Agent
from test_chat_preparation_trail import scripted_model
from test_chat_session_trail import chat_capture as chat_capture  # noqa: PLC0414
from test_chat_startup import (
    startup_dependencies as startup_dependencies,  # noqa: PLC0414
)
from test_retrieval import COVERAGE, Branch, candidate, coordinator

from knowledge_map.chat_startup import ChatDependencies, chat_dependencies
from knowledge_map.chat_telemetry import ChatSessionSettings
from knowledge_map.core.chat import CHAT_INSTRUCTIONS
from knowledge_map.core.question_preparation import QUERY_REWRITER_INSTRUCTIONS
from knowledge_map.evaluation import load_data_set, run_data_set, write_report
from knowledge_map.evaluation.data_set import (
    EvaluationCase,
    EvaluationDataSet,
    EvaluationSplit,
    LabelQuality,
)
from knowledge_map.evaluation.tasks import chat as task_module
from knowledge_map.evaluation.tasks import task_named
from knowledge_map.evaluation.tasks.chat import ChatCaseLifecycle, ChatInput
from knowledge_map.schemas import DeploymentKind, ModelDeployment
from knowledge_map.schemas.evidence import EvidenceContextLimits
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.query_preparation import (
    QueryRewriteProposal,
    QuestionAssessment,
)
from knowledge_map.schemas.retrieval import (
    BranchScore,
    RetrievalAnswer,
    RetrievalBranch,
)

DEPLOYMENT = ModelDeployment(kind=DeploymentKind.LOCAL, model="test-chat")


def test_current_training_cases_copy_targets_without_inventing_answer_labels():
    task = task_named("chat")
    data_set = load_data_set(
        "evals/unlabeled/chat.yaml",
        input_type=task.input_type,
        output_type=task.output_type,
        metadata_type=task.metadata_type,
    )
    source = yaml.safe_load(
        Path(
            "work/initiatives/useful-graph-retrieval/query-construction/cases.yaml"
        ).read_text()
    )
    assert len(data_set.cases) == 36
    assert {c.id: c.task_input.question for c in data_set.cases[:25]} == {
        c["id"]: c["question"] for c in source["cases"]
    }
    assert all(c.expected_output is None for c in data_set.cases)
    assert all(c.split is EvaluationSplit.TRAINING for c in data_set.cases)
    assert task.label_quality is LabelQuality.UNLABELED
    assert not task.evaluators


def fake_dependencies(
    monkeypatch, *, assessment=None, guidance=None, failed_branch=None
):
    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    if failed_branch:

        async def fail(*args, **kwargs):
            raise RuntimeError("private database diagnostic")

        branches[failed_branch].retrieve = fail

    @asynccontextmanager
    async def dependencies(*, chat_deployment, capabilities):
        assert chat_deployment == DEPLOYMENT
        rewriter = Agent(
            scripted_model(
                [{"question": "Which organizations support AB 1?", "relational": True}]
            ),
            name="query_rewriter",
            instructions=QUERY_REWRITER_INSTRUCTIONS,
            output_type=QueryRewriteProposal,
            capabilities=capabilities,
        )
        chat = Agent(
            scripted_model(
                [
                    assessment or {"status": "allowed"},
                    guidance or {"introduction": "Read the available reporting."},
                ]
            ),
            name="chat_agent",
            instructions=CHAT_INSTRUCTIONS,
            output_type=QuestionAssessment,
            retries=0,
            capabilities=capabilities,
        )
        yield ChatDependencies(
            rewriter,
            chat,
            coordinator(branches),
            COVERAGE.model_copy(
                update={
                    "entries": (
                        COVERAGE.entries[0].model_copy(
                            update={"collection_id": "calmatters"}
                        ),
                    ),
                }
            ),
            DEPLOYMENT,
            DEPLOYMENT,
            ChatSessionSettings(
                code_revision="abc123",
                worktree_dirty=False,
                model_deployments={"chat_agent": DEPLOYMENT.model_dump(mode="json")},
                embedding_settings={"model": "test-embedding"},
                prompt_hashes={},
                fusion_settings=FusionConfig(),
                evidence_limits=EvidenceContextLimits(),
                coverage_observed_at="2026-09-28T00:00:00+00:00",
            ),
        )

    monkeypatch.setattr(task_module, "chat_dependencies", dependencies)
    return branches


def run_one():
    data_set = EvaluationDataSet(
        task="chat",
        description="One full Chat Session",
        cases=(
            EvaluationCase(
                id="case-1",
                description="Support question",
                split=EvaluationSplit.TRAINING,
                task_input=ChatInput(question="Who backed AB 1?"),
            ),
        ),
    )
    return run_data_set(
        data_set,
        task=task_module.build_task(DEPLOYMENT, data_set),
        evaluators=(),
        case_lifecycle=ChatCaseLifecycle,
    )


def test_report_contains_rendered_answer_sources_requests_and_stage_outcomes(
    monkeypatch,
    chat_capture,
    tmp_path,
):
    fake_dependencies(monkeypatch, failed_branch=RetrievalBranch.DENSE)
    report = run_one()
    assert not report.failures
    case = report.cases[0]
    output = case.output
    assert output.failure is None
    assert isinstance(output.answer, RetrievalAnswer)
    assert "The union supports AB 1." in output.rendered_text
    assert output.answer.evidence.sources[0].passages[0].provenance == "stored_chunk"
    assert len(output.messages) == 3
    assert [r["component"] for r in output.messages] == [
        "query_rewriter",
        "chat_agent",
        "chat_agent",
    ]
    assert all(r["messages"][-1]["kind"] == "response" for r in output.messages)
    assert all(r["request_parameters"]["instruction_parts"] for r in output.messages)
    assert "The union supports AB 1." in json.dumps(output.messages[-1])
    stages = case.attributes["stage_observations"]
    failed = [s for s in stages if s["attributes"].get("status") == "failed"]
    assert any(s["attributes"].get("branch") == "dense" for s in failed)
    assert case.attributes["chat_session_id"] == output.chat_session_id
    assert not case.assertions
    path = write_report(
        report,
        task="chat",
        deployment=DEPLOYMENT,
        data_set_path="evals/unlabeled/chat.yaml",
        label_quality=LabelQuality.UNLABELED,
        root=tmp_path,
    )
    saved = json.loads(path.read_text())
    assert saved["label_quality"] == "unlabeled"
    assert saved["report"]["cases"][0]["output"]["messages"]
    assert "private database diagnostic" not in path.read_text()


def test_report_keeps_only_dense_count_of_full_text_candidates(
    monkeypatch, chat_capture, tmp_path
):
    branches = fake_dependencies(monkeypatch)
    full_text = RetrievalBranch.FULL_TEXT
    dense = RetrievalBranch.DENSE

    def scored(rank: int, score: float):
        found = candidate(full_text, chunk=f"ft-{rank}", rank=rank)
        return found.model_copy(
            update={
                "ranking": found.ranking.model_copy(
                    update={"score": BranchScore(score)}
                )
            }
        )

    branches[full_text].candidates = (
        scored(4, 4.0),
        scored(1, 10.0),
        scored(3, 6.0),
        scored(2, 8.0),
    )
    branches[dense].candidates = (
        candidate(dense, chunk="dense-1", rank=1),
        candidate(dense, chunk="dense-2", rank=2),
    )

    report = run_one()
    output = report.cases[0].output
    original = next(
        outcome
        for outcome in output.answer.evidence.execution.outcomes
        if outcome.branch == full_text
    )
    assert len(original.candidates) == 4

    path = write_report(
        report,
        task="chat",
        deployment=DEPLOYMENT,
        data_set_path="evals/unlabeled/chat.yaml",
        label_quality=LabelQuality.UNLABELED,
        root=tmp_path,
    )
    saved = json.loads(path.read_text())["report"]["cases"][0]["output"]
    branch = next(
        outcome
        for outcome in saved["answer"]["evidence"]["execution"]["outcomes"]
        if outcome["branch"] == "full_text"
    )
    assert [item["ranking"]["rank"] for item in branch["candidates"]] == [1, 2]
    assert branch["candidate_summary"] == {
        "total_retrieved": 4,
        "dense_retrieved": 2,
        "retained_count": 2,
        "unlisted_count": 2,
        "scored_count": 4,
        "unlisted_scored_count": 2,
        "all_avg_score": 7.0,
        "unlisted_avg_score": 5.0,
        "unlisted_min_score": 4.0,
        "unlisted_max_score": 6.0,
        "unlisted_rank_min": 3,
        "unlisted_rank_max": 4,
    }
    assert any(
        passage["candidate"]["chunk_id"] == "ft-3"
        for source in saved["answer"]["evidence"]["sources"]
        for passage in source["passages"]
    )


def test_report_summarizes_unscored_full_text_candidates_when_dense_fails():
    document = {
        "execution": {
            "outcomes": [
                {
                    "branch": "full_text",
                    "status": "succeeded",
                    "candidates": [
                        {"chunk_id": "a", "ranking": {"rank": 1, "score": None}},
                        {"chunk_id": "b", "ranking": {"rank": 2, "score": 4.0}},
                    ],
                },
                {"branch": "dense", "status": "failed"},
            ]
        }
    }

    result = task_module.compact_retrieval_for_report(document)
    full_text = result["execution"]["outcomes"][0]

    assert full_text["candidates"] == []
    assert full_text["candidate_summary"]["total_retrieved"] == 2
    assert full_text["candidate_summary"]["dense_retrieved"] == 0
    assert full_text["candidate_summary"]["unlisted_count"] == 2
    assert full_text["candidate_summary"]["unlisted_scored_count"] == 1
    assert full_text["candidate_summary"]["unlisted_avg_score"] == 4.0
    assert task_module.compact_retrieval_for_report(result) is result
    assert (
        result["execution"]["outcomes"][0]["candidate_summary"]["total_retrieved"] == 2
    )


def test_declined_question_is_retained_without_retrieval(monkeypatch, chat_capture):
    branches = fake_dependencies(
        monkeypatch,
        assessment={
            "status": "declined",
            "explanation": "This question is outside scope.",
        },
    )
    output = run_one().cases[0].output
    assert output.preparation.status == "declined"
    assert output.answer is None
    assert output.rendered_text == "This question is outside scope."
    assert len(output.messages) == 2
    assert not any(branch.requests for branch in branches.values())


def test_invalid_guidance_keeps_retrieved_context_in_failed_case(
    monkeypatch, chat_capture
):
    fake_dependencies(
        monkeypatch,
        guidance={
            "source_notes": [
                {"source_article_id": "invented", "note": "Unsupported source"}
            ]
        },
    )
    report = run_one()
    assert not report.failures
    output = report.cases[0].output
    assert output.failure.stage == "retrieval_and_guidance"
    assert output.failure.exception_type == "ValidationError"
    assert output.failure.kind == "validation"
    assert output.retrieval.sources
    assert output.retrieval.execution.outcomes
    assert "The union supports AB 1." in json.dumps(output.messages[-1])
    assert any(
        s["name"] == "chat_session.guidance"
        and s["attributes"].get("status") == "failed"
        for s in report.cases[0].attributes["stage_observations"]
    )


def test_startup_failure_stays_in_population(monkeypatch, chat_capture):
    @asynccontextmanager
    async def unavailable(**kwargs):
        raise RuntimeError("private credential")
        yield

    monkeypatch.setattr(task_module, "chat_dependencies", unavailable)
    report = run_one()
    assert not report.failures
    output = report.cases[0].output
    assert output.failure.stage == "startup"
    assert output.chat_session_id is None
    assert "private credential" not in output.model_dump_json()


def test_failed_model_request_is_captured_with_input(chat_capture):
    async def exercise():
        records = []
        from pydantic_ai.models.function import FunctionModel

        def unavailable(messages, info):
            raise httpx.ConnectError("private provider diagnostic")

        agent = Agent(
            FunctionModel(unavailable),
            name="failing",
            capabilities=[task_module.capture_messages(records)],
        )
        with pytest.raises(httpx.ConnectError):
            await agent.run("Question that must remain inspectable")
        assert records[0]["status"] == "failed"
        assert records[0]["exception_type"] == "ConnectError"
        assert "Question that must remain inspectable" in json.dumps(records)
        assert "private provider diagnostic" not in json.dumps(records)

    asyncio.run(exercise())


def test_chat_startup_uses_explicit_deployment_for_chat_and_structural_agents(
    startup_dependencies,
    chat_capture,
):
    async def exercise():
        async with chat_dependencies(chat_deployment=DEPLOYMENT) as dependencies:
            assert dependencies.chat_deployment == DEPLOYMENT
            assert dependencies.chat_agent.model.model_name == "test-chat"
            settings = dependencies.start_settings.model_deployments
            assert settings["jev_binder"]["model"] == "test-chat"
            assert settings["query_rewriter"]["model"] == "rewriter-test"

    asyncio.run(exercise())
