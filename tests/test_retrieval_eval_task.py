"""Reference evidence is measured at each stage without hiding failures."""

import hashlib
import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError
from test_chat_eval_task import DEPLOYMENT, fake_dependencies
from test_chat_session_trail import chat_capture as chat_capture  # noqa: PLC0414
from test_retrieval import COVERAGE, Branch, candidate, coordinator, rewrite

from knowledge_map.core.evidence import render_evidence_context
from knowledge_map.evaluation import load_data_set, run_data_set, write_report
from knowledge_map.evaluation.data_set import EvaluationCase, EvaluationDataSet
from knowledge_map.evaluation.tasks import chat, task_named
from knowledge_map.evaluation.tasks import retrieval as task_module
from knowledge_map.evaluation.tasks.retrieval import (
    EvidenceRequirement,
    ReferenceAnswer,
    RetrievalExpectation,
    RetrievalOutput,
    RetrievedReferenceEvidence,
    ranked_ids,
    retrieval_scores,
)
from knowledge_map.schemas.evidence import EvidenceContextLimits
from knowledge_map.schemas.retrieval import EvidenceAssemblyFailure, RetrievalBranch


def expectation(ids=("a", "b"), *, groups=None, grain="article_chunk"):
    return RetrievalExpectation(
        grain=grain,
        relevant_ids=ids,
        answers=(
            ReferenceAnswer(
                groups=tuple(
                    EvidenceRequirement(kind=f"hop-{i}", ids=group)
                    for i, group in enumerate(groups or [(id,) for id in ids])
                )
            ),
        ),
    )


def values(scores):
    return {key: result.value for key, result in scores.items()}


def evaluate(output, expected, *, relational=False):
    return values(
        RetrievedReferenceEvidence().evaluate(
            SimpleNamespace(
                inputs=rewrite(relational),
                output=output,
                expected_output=expected,
            )
        )
    )


def test_recall_and_complete_evidence_distinguish_a_missing_hop():
    expected = expectation()
    scores = values(
        retrieval_scores(("noise", "b", "a"), expected, prefix="dense", ks=(1, 2, 3))
    )
    assert scores["dense_recall_at_1"] == 0
    assert scores["dense_recall_at_2"] == 0.5
    assert scores["dense_complete_evidence_at_2"] == 0
    assert scores["dense_complete_evidence_at_3"] == 1
    assert scores["dense_reciprocal_rank"] == 0.5
    assert (
        values(retrieval_scores((), expected, prefix="dense", ks=(5,)))[
            "dense_recall_at_5"
        ]
        == 0
    )


def test_alternative_witnesses_and_a_shared_chunk_can_satisfy_both_hops():
    expected = expectation(("a", "b", "c"), groups=(("a", "b"), ("b", "c")))
    scores = values(retrieval_scores(("b",), expected, prefix="fused", ks=(1,)))
    assert scores["fused_recall_at_1"] == pytest.approx(1 / 3)
    assert scores["fused_complete_evidence_at_1"] == 1


def test_best_rank_deduplication_and_source_article_grain():
    branch = RetrievalBranch.FULL_TEXT
    candidates = (
        candidate(branch, chunk="b", rank=3),
        candidate(branch, chunk="a", rank=1),
        candidate(branch, chunk="a", rank=2),
    )
    assert ranked_ids(candidates, "article_chunk") == ("a", "b")
    assert ranked_ids(candidates, "source_article") == (
        "https://example.com/a",
        "https://example.com/b",
    )
    same_article = tuple(
        c.model_copy(update={"source_article_id": "article"}) for c in candidates
    )
    assert ranked_ids(same_article, "source_article") == ("article", "article")


@pytest.mark.parametrize(
    "ids,groups", [(("a", "a"), None), (("a",), (("b",),)), (("a", "b"), (("a",),))]
)
def test_invalid_reference_denominators_are_rejected(ids, groups):
    with pytest.raises(ValidationError):
        expectation(ids, groups=groups)


@pytest.mark.parametrize("ks", [(), (0,), (True,), (1.5,), (51,)])
def test_invalid_cutoffs_are_rejected(ks):
    with pytest.raises(ValueError):
        RetrievedReferenceEvidence(ks=ks)


def test_startup_failure_scores_zero_and_does_not_create_a_structural_score():
    scores = evaluate(
        RetrievalOutput(
            failure=chat.ChatFailure(
                stage="startup",
                kind="execution",
                exception_type="RuntimeError",
                diagnostic="Unavailable",
            )
        ),
        expectation(),
    )
    assert scores["dense_recall_at_5"] == scores["full_text_recall_at_5"] == 0
    assert scores["context_recall"] == scores["fused_recall_at_5"] == 0
    assert scores["retrieval_attempt_completed"] is False
    assert not any(key.startswith("structural_") for key in scores)


def test_assembly_loss_keeps_branch_and_fused_scores():
    import asyncio

    branches = {b: Branch(b) for b in RetrievalBranch}
    pipeline = coordinator(
        branches, context_limits=EvidenceContextLimits(max_passages=1)
    )
    package = asyncio.run(
        pipeline.run(
            rewrite(),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
        )
    )
    output = RetrievalOutput(
        result=package, fused=task_module.fuse_candidates(package.execution)
    )
    scores = evaluate(output, expectation(("dense", "full_text")))
    assert scores["dense_recall_at_5"] == 0.5
    assert scores["fused_recall_at_5"] == 1
    assert scores["context_recall"] == 0.5
    assert scores["context_complete_evidence"] == 0
    failed = output.model_copy(
        update={"result": EvidenceAssemblyFailure(execution=package.execution)}
    )
    scores = evaluate(failed, expectation(("dense", "full_text")))
    assert scores["fused_recall_at_5"] == 1
    assert scores["context_recall"] == 0
    assert scores["evidence_assembled"] is False


def test_all_25_cases_preserve_questions_provenance_routing_and_article_grain():
    task = task_named("retrieval")
    data_set = load_data_set(
        "evals/silver/retrieval.yaml",
        input_type=task.input_type,
        output_type=task.output_type,
        metadata_type=task.metadata_type,
    )
    root = Path("work/initiatives/useful-graph-retrieval/query-construction")
    source = yaml.safe_load((root / "cases.yaml").read_text())
    reference = json.loads((root / "verified-results.json").read_text())
    evidence = {e["id"]: e for e in reference["evidence"]}
    assert len(data_set.cases) == 25
    assert {c.id: c.task_input.question for c in data_set.cases} == {
        c["id"]: c["question"] for c in source["cases"]
    }
    for c, observed in zip(data_set.cases, reference["cases"], strict=True):
        assert c.split.value == "training"
        assert (
            c.metadata.reference_sha256
            == hashlib.sha256((root / "verified-results.json").read_bytes()).hexdigest()
        )
        assert c.task_input.relational == (c.metadata.family not in ("E1", "E2"))
        relevant = {
            id
            for r in observed["rows"]
            for g in r["evidence_groups"]
            for id in g["ids"]
        }
        if c.metadata.family == "E3":
            relevant = {evidence[id]["article_id"] for id in relevant}
            assert c.expected_output.grain == "source_article"
        assert set(c.expected_output.relevant_ids) == relevant


def test_production_wiring_failed_branch_and_report_retain_bounded_evidence(
    monkeypatch, chat_capture, tmp_path
):
    branches = fake_dependencies(
        monkeypatch, failed_branch=RetrievalBranch.STRUCTURAL, prepare_question=False
    )
    branches[RetrievalBranch.FULL_TEXT].candidates = tuple(
        candidate(RetrievalBranch.FULL_TEXT, chunk=f"ft-{rank}", rank=rank)
        for rank in range(1, 6)
    )
    monkeypatch.setattr(task_module, "chat_dependencies", chat.chat_dependencies)
    data_set = EvaluationDataSet(
        task="retrieval",
        description="Independent retrieval",
        cases=(
            EvaluationCase(
                id="fixed-question",
                description="Reference chunks",
                task_input=rewrite(True),
                expected_output=expectation(("ft-5", "dense")),
            ),
        ),
    )
    task = task_named("retrieval")
    report = run_data_set(
        data_set,
        task=task.build(DEPLOYMENT, data_set),
        evaluators=task.evaluators,
        case_lifecycle=task.case_lifecycle,
    )
    assert not report.failures
    case = report.cases[0]
    assert not case.evaluator_failures
    assert case.attributes["chat_session_id"] == case.output.chat_session_id
    assert any(
        s["attributes"].get("status") == "failed"
        for s in case.attributes["stage_observations"]
    )
    assert case.scores["fused_recall_at_5"].value == 0.5
    assert case.scores["context_recall"].value == 1
    assert case.assertions["structural_completed"].value is False
    assert case.output.answer.evidence is case.output.result
    assert "Read the available reporting." in case.output.rendered_text
    assert case.assertions["answer_generated"].value is True
    assert len(case.output.messages) == 1  # Guidance only; no rewrite or assessment.
    exchange = case.output.messages[0]
    assert exchange["component"] == "chat_agent"
    prompts = [
        p["content"]
        for m in exchange["messages"]
        for p in m["parts"]
        if p["part_kind"] == "user-prompt"
    ]
    assert prompts == [
        rewrite(True).question,
        render_evidence_context(case.output.result),
    ]
    assert "relevant_ids" not in json.dumps(exchange)
    assert branches[RetrievalBranch.FULL_TEXT].requests[0][0].rewrite == rewrite(True)
    path = write_report(
        report,
        task="retrieval",
        deployment=DEPLOYMENT,
        data_set_path="evals/silver/retrieval.yaml",
        label_quality=task.label_quality,
        root=tmp_path,
    )
    document = json.loads(path.read_text())
    saved = document["report"]["cases"][0]["output"]
    assert len(saved["branches"][0]["candidates"]) == 5
    assert "fused" not in saved
    assert saved["answer"]["introduction"] == case.output.answer.introduction
    assert "evidence" not in saved["answer"]
    assert saved["rendered_text"] == case.output.rendered_text
    assert document["retrieval_report"]["configurations"][0]["fusion_settings"]
    assert "stage_observations" not in document["report"]["cases"][0]["attributes"]


def test_generation_failure_keeps_retrieval_metrics_and_context(
    monkeypatch, chat_capture
):
    fake_dependencies(
        monkeypatch,
        prepare_question=False,
        guidance={
            "source_notes": [
                {"source_article_id": "unselected", "note": "Invalid citation"}
            ]
        },
    )
    monkeypatch.setattr(task_module, "chat_dependencies", chat.chat_dependencies)
    import asyncio

    output = asyncio.run(task_module.build_task(DEPLOYMENT, None)(rewrite(True)))
    assert output.failure.stage == "guidance"
    assert output.answer is None
    assert output.rendered_text is None
    assert output.result.sources
    scores = evaluate(output, expectation(("full_text", "dense")), relational=True)
    assert scores["retrieval_attempt_completed"] is True
    assert scores["evidence_assembled"] is True
    assert scores["answer_generated"] is False
    assert scores["fused_recall_at_5"] == 1
    assert scores["context_recall"] == 1


def test_assembly_failure_does_not_call_generation(monkeypatch, chat_capture):
    fake_dependencies(monkeypatch, prepare_question=False)

    async def fail_grounding(*args, **kwargs):
        raise LookupError("Unavailable grounding")

    monkeypatch.setattr("test_retrieval.load_grounding", fail_grounding)
    monkeypatch.setattr(task_module, "chat_dependencies", chat.chat_dependencies)
    import asyncio

    output = asyncio.run(task_module.build_task(DEPLOYMENT, None)(rewrite(True)))
    assert isinstance(output.result, EvidenceAssemblyFailure)
    assert not output.messages
    assert output.answer is None
    assert evaluate(output, expectation(), relational=True)["answer_generated"] is False


def test_builder_rejects_mismatched_reference_and_preserves_dataset(tmp_path):
    builder = runpy.run_path("scripts/build_retrieval_eval.py")
    REFERENCE_DIR, build_document = builder["REFERENCE_DIR"], builder["build_document"]

    doc = build_document(
        REFERENCE_DIR / "cases.yaml", REFERENCE_DIR / "verified-results.json"
    )
    assert doc == yaml.safe_load(Path("evals/silver/retrieval.yaml").read_text())
    reference = json.loads((REFERENCE_DIR / "verified-results.json").read_text())
    reference["cases_sha256"] = "wrong"
    target = tmp_path / "reference.json"
    target.write_text(json.dumps(reference))
    with pytest.raises(ValueError, match="do not match"):
        build_document(REFERENCE_DIR / "cases.yaml", target)


def test_reference_precision_counts_matching_chunk_slots_and_uses_k_denominator():
    scores = values(
        retrieval_scores(
            ("noise", "a", "b"), expectation(), prefix="fused", ks=(1, 2, 5)
        )
    )
    assert scores["fused_precision_at_1"] == 0
    assert scores["fused_precision_at_2"] == 0.5
    assert scores["fused_precision_at_5"] == 0.4
    assert (
        values(retrieval_scores((), expectation(), prefix="fused", ks=(5,)))[
            "fused_precision_at_5"
        ]
        == 0
    )
    article = expectation(("article",), grain="source_article")
    scores = values(
        retrieval_scores(
            ("article", "article", "noise"), article, prefix="dense", ks=(2, 5)
        )
    )
    assert scores["dense_precision_at_2"] == 1
    assert scores["dense_precision_at_5"] == 0.4
    assert scores["dense_recall_at_2"] == 1
