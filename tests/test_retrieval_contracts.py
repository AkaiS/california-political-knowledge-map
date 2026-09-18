"""Contracts shared by retrieval, Evidence Assembly, and the Chat Agent."""

import pytest
from pydantic import ValidationError

from knowledge_map.schemas.query_preparation import QueryRewrite, QuestionAssessment
from knowledge_map.schemas.retrieval import (
    BranchCandidate,
    BranchScore,
    CoverageDescription,
    EvidenceAssemblyFailure,
    EvidencePackage,
    FusedCandidate,
    MonthlyCoverage,
    RetrievalAnswer,
    RetrievalBranch,
    RetrievalExecutionResult,
    RetrievalFailureLog,
    RetrievalRequest,
)


def approved_rewrite(relational=True):
    return QueryRewrite(
        question="Which organizations lobbied for AB 186 in 2025-2026?",
        relational=relational,
        assessment=QuestionAssessment(status="allowed"),
    )


@pytest.mark.parametrize(
    ("relational", "expected"),
    [
        (True, ("full_text", "dense", "structural")),
        (False, ("full_text", "dense")),
    ],
)
def test_retrieval_accepts_only_the_approved_rewrite_and_derives_branches(
    relational, expected
):
    request = RetrievalRequest(rewrite=approved_rewrite(relational))
    assert request.expected_branches == expected
    assert RetrievalRequest.model_validate_json(request.model_dump_json()) == request
    for extra in (
        {"original_question": "The original wording"},
        {"expected_branches": ["dense"]},
    ):
        with pytest.raises(ValidationError):
            RetrievalRequest.model_validate({**request.model_dump(), **extra})
    with pytest.raises(ValidationError):
        RetrievalRequest.model_validate(
            {"rewrite": {"question": "Unapproved proposal", "relational": True}}
        )


def test_declined_question_cannot_enter_retrieval():
    with pytest.raises(ValidationError, match="Declined"):
        RetrievalRequest(
            rewrite=QueryRewrite(
                question="What was the governor's private motive?",
                relational=True,
                assessment=QuestionAssessment(
                    status="declined", explanation="Private motives are unsupported."
                ),
            )
        )


def candidate_values(branch="full_text", chunk_id="article-a#chunk_0", rank=1):
    kind, matched_field = {
        "full_text": ("entity_name", "name"),
        "dense": ("chunk_embedding", "embedding"),
        "structural": ("typed_traversal", None),
    }[branch]
    return {
        "chunk_id": chunk_id,
        "source_article_id": chunk_id.split("#", 1)[0],
        "ranking": {"branch": branch, "rank": rank, "score": 0.8},
        "routes": [
            {
                "kind": kind,
                "matched_field": matched_field,
                "entry_node": {
                    "id": "org-disney",
                    "label": "Organization",
                    "element_id": "node:17",
                },
                "graph_claims": [],
            }
        ],
    }


def test_fused_candidate_retains_branch_ranks_routes_and_claim_identity():
    structural = candidate_values("structural", rank=3)
    structural["routes"][0]["graph_claims"] = [
        {
            "source": {
                "id": "org-disney",
                "label": "Organization",
                "element_id": "node:17",
            },
            "target": {"id": "bill-ab186", "label": "Bill", "element_id": "node:24"},
            "relationship_type": "LOBBIED_FOR",
            "claim_key": {},
            "chunk_ids": ["article-a#chunk_0"],
            "source_article_ids": [],
            "needs_review": True,
        }
    ]
    full_text = BranchCandidate.model_validate(candidate_values(rank=2))
    graph = BranchCandidate.model_validate(structural)
    fused = FusedCandidate(
        chunk_id="article-a#chunk_0",
        rank=1,
        fusion_score=0.075,
        contributions=(full_text, graph),
    )
    restored = FusedCandidate.model_validate_json(fused.model_dump_json())
    assert restored.contributions[0].ranking.model_dump() == {
        "branch": "full_text",
        "rank": 2,
        "score": 0.8,
    }
    assert restored.contributions[1].ranking.rank == 3
    claim = restored.contributions[1].routes[0].graph_claims[0]
    assert (claim.source.id, claim.source.element_id, claim.needs_review) == (
        "org-disney",
        "node:17",
        True,
    )
    assert claim.chunk_ids == ("article-a#chunk_0",)
    with pytest.raises(TypeError):
        _ = full_text.ranking < graph.ranking  # ty: ignore[unsupported-operator]
    with pytest.raises(TypeError):
        _ = full_text.ranking.score < graph.ranking.score  # ty: ignore[unsupported-operator]
    assert isinstance(graph.ranking.score, BranchScore)
    with pytest.raises(ValidationError):
        FusedCandidate.model_validate(
            {**fused.model_dump(), "fusion_score": graph.ranking.score}
        )
    with pytest.raises(ValidationError, match="same Article Chunk"):
        FusedCandidate(
            chunk_id="unrelated-chunk",
            rank=1,
            fusion_score=0.075,
            contributions=(full_text,),
        )
    other_source = BranchCandidate.model_validate(
        {
            **candidate_values("dense", rank=2),
            "source_article_id": "article-b",
        }
    )
    with pytest.raises(ValidationError, match="same Source Article"):
        FusedCandidate(
            chunk_id="article-a#chunk_0",
            rank=1,
            fusion_score=0.075,
            contributions=(full_text, other_source),
        )


@pytest.mark.parametrize(
    ("relationship_type", "chunk_ids", "source_article_ids"),
    [
        ("LOBBIED_FOR", [], []),
        ("LOBBIED_FOR", ["article-a#chunk_0"], ["article-a"]),
        ("LOBBIED_FOR", [], ["article-a"]),
        ("DISCUSSES_TOPIC", ["article-a#chunk_0"], []),
        ("ABOUT_TOPIC", ["article-a#chunk_0"], ["article-a"]),
    ],
)
def test_graph_claim_requires_provenance_at_its_decision_grain(
    relationship_type, chunk_ids, source_article_ids
):
    values = candidate_values("structural")
    values["routes"][0]["graph_claims"] = [
        {
            "source": {"id": "org-disney", "label": "Organization"},
            "target": {"id": "bill-ab186", "label": "Bill"},
            "relationship_type": relationship_type,
            "claim_key": {},
            "chunk_ids": chunk_ids,
            "source_article_ids": source_article_ids,
        }
    ]
    with pytest.raises(ValidationError, match="claim"):
        BranchCandidate.model_validate(values)


def execution_values(structural_status="succeeded", relational=True):
    structural = {"branch": "structural", "status": structural_status}
    if structural_status == "succeeded":
        structural["candidates"] = []
    if structural_status == "skipped":
        structural["reason"] = "non_relational"
    return {
        "request": {"rewrite": approved_rewrite(relational).model_dump()},
        "outcomes": [
            {
                "branch": "full_text",
                "status": "succeeded",
                "candidates": [candidate_values()],
            },
            {"branch": "dense", "status": "succeeded", "candidates": []},
            structural,
        ],
    }


def test_execution_keeps_structural_empty_failed_and_skipped_distinct():
    empty = RetrievalExecutionResult.model_validate(execution_values())
    failed = RetrievalExecutionResult.model_validate(execution_values("failed"))
    skipped = RetrievalExecutionResult.model_validate(
        execution_values("skipped", False)
    )
    assert [result.outcomes[2].status for result in (empty, failed, skipped)] == [
        "succeeded",
        "failed",
        "skipped",
    ]
    assert [result.failed_branches for result in (empty, failed, skipped)] == [
        (),
        ("structural",),
        (),
    ]
    assert empty.expected_branches == ("full_text", "dense", "structural")
    assert skipped.expected_branches == ("full_text", "dense")
    assert skipped.model_dump(mode="json")["expected_branches"] == [
        "full_text",
        "dense",
    ]
    assert empty.evidence_by_branch[RetrievalBranch.STRUCTURAL] == ()
    assert "structural" not in failed.evidence_by_branch
    assert "structural" not in skipped.evidence_by_branch
    for result in (empty, failed, skipped):
        assert (
            result.evidence_by_branch[RetrievalBranch.FULL_TEXT][0].chunk_id
            == "article-a#chunk_0"
        )
        assert "status" not in result.model_dump()
        assert (
            RetrievalExecutionResult.model_validate_json(result.model_dump_json())
            == result
        )


@pytest.mark.parametrize(
    "change",
    [
        "omit_branch",
        "duplicate_branch",
        "skip_expected",
        "run_unexpected",
        "foreign_score",
        "wrong_expectation",
    ],
)
def test_execution_rejects_missing_or_contradictory_branch_facts(change):
    values = execution_values()
    if change == "omit_branch":
        values["outcomes"].pop()
    elif change == "duplicate_branch":
        values["outcomes"].append(values["outcomes"][0])
    elif change == "skip_expected":
        values["outcomes"][2] = {
            "branch": "structural",
            "status": "skipped",
            "reason": "non_relational",
        }
    elif change == "run_unexpected":
        values["request"]["rewrite"]["relational"] = False
    elif change == "foreign_score":
        values["outcomes"][0]["candidates"][0]["ranking"]["branch"] = "dense"
    elif change == "wrong_expectation":
        values["expected_branches"] = ["dense"]
    with pytest.raises(ValidationError):
        RetrievalExecutionResult.model_validate(values)


@pytest.mark.parametrize(
    "change", ["foreign_route", "wrong_field", "nonfinite_score", "zero_rank"]
)
def test_branch_candidate_keeps_its_score_and_match_on_the_recorded_route(change):
    values = candidate_values()
    if change == "foreign_route":
        values["routes"] = candidate_values("dense")["routes"]
    elif change == "wrong_field":
        values["routes"][0]["matched_field"] = "title"
    elif change == "nonfinite_score":
        values["ranking"]["score"] = float("nan")
    elif change == "zero_rank":
        values["ranking"]["rank"] = 0
    with pytest.raises(ValidationError):
        BranchCandidate.model_validate(values)


@pytest.mark.parametrize("branch", ["structural", "full_text", "dense"])
def test_failure_diagnostics_stay_in_log_values_not_branch_outcomes(branch):
    diagnostic = RetrievalFailureLog(
        branch=branch,
        stage="deadline",
        failure_kind="deadline_exhausted",
        attempts_consumed=2,
        safe_diagnostic="Retrieval deadline reached.",
    )
    assert diagnostic.model_dump() == {
        "branch": branch,
        "stage": "deadline",
        "failure_kind": "deadline_exhausted",
        "attempts_consumed": 2,
        "safe_diagnostic": "Retrieval deadline reached.",
    }
    assert diagnostic.deadline_exhausted is True
    values = execution_values("failed")
    for field in (
        "exception",
        "model_output",
        "safe_diagnostic",
        "stage",
        "failure_kind",
    ):
        values["outcomes"][2] = {
            "branch": "structural",
            "status": "failed",
            field: "secret",
        }
        with pytest.raises(ValidationError):
            RetrievalExecutionResult.model_validate(values)


@pytest.mark.parametrize(
    "stage",
    [
        "schema_filtering",
        "typed_selection",
        "wiring",
        "binding",
        "validation",
        "hop_bound",
        "cypher_execution",
        "hydration",
    ],
)
def test_structural_failure_logs_identify_the_stage_and_attempts(stage):
    value = RetrievalFailureLog(
        branch="structural",
        stage=stage,
        failure_kind="validation",
        attempts_consumed=3,
        safe_diagnostic="Construction rejected by validation.",
    )
    assert value.stage == stage and value.attempts_consumed == 3
    assert value.deadline_exhausted is False


def coverage_values():
    return {
        "entries": [
            {
                "collection_id": "calmatters",
                "name": "CalMatters",
                "kind": "publication",
                "description": "Reporting on California politics.",
                "limitations": ["Reporting does not establish a complete roll call."],
                "availability": {"available_count": 98, "expected_count": None},
                "date_basis": "publication_date",
                "earliest_date": "2026-07-01",
                "latest_date": "2026-09-08",
            }
        ],
    }


def test_coverage_keeps_observed_availability_separate_from_known_completeness():
    coverage = CoverageDescription.model_validate(coverage_values())
    assert coverage.entries[0].availability.percentage is None
    assert "monthly" not in coverage.model_dump()
    july = MonthlyCoverage.model_validate(
        {
            "collection_id": "calmatters",
            "month": "2026-07",
            "availability": {"available_count": 40, "expected_count": 50},
        }
    )
    assert july.availability.percentage == 80.0
    assert (
        CoverageDescription.model_validate_json(coverage.model_dump_json()) == coverage
    )
    for changes in (
        {"availability": {"available_count": 98, "percentage": 90}},
        {"availability": {"available_count": 98, "expected_count": 90}},
        {"date_basis": "event_date"},
        {"refresh_status": "incomplete"},
    ):
        values = coverage_values()
        values["entries"][0].update(changes)
        with pytest.raises(ValidationError):
            CoverageDescription.model_validate(values)


def evidence_values():
    execution = execution_values("failed")
    execution["request"]["rewrite"]["assessment"] = {
        "status": "deferred",
        "explanation": "A complete lobbying register is unavailable.",
        "recoverable_portion": "Reporting may identify individual organizations.",
    }
    return {
        "execution": execution,
        "sources": [
            {
                "citation": {
                    "source_article_id": "article-a",
                    "title": "Lobbying on AB 186",
                    "url": "https://example.org/article-a",
                    "published_date": "2026-07-01",
                },
                "passages": [
                    {
                        "source_article_id": "article-a",
                        "text": "Disney lobbied for AB 186.",
                        "start": 12,
                        "end": 38,
                        "verification": "original_story",
                        "candidate": {
                            "chunk_id": "article-a#chunk_0",
                            "rank": 1,
                            "fusion_score": 0.03,
                            "contributions": [candidate_values()],
                        },
                    }
                ],
            }
        ],
        "coverage": coverage_values(),
        "context": {
            "unit": "tokens",
            "limit": 1000,
            "max_passages": 10,
            "used": 120,
            "omitted_passages": 2,
        },
    }


def test_evidence_package_and_answer_retain_sources_limits_and_failure_disclosure():
    evidence = EvidencePackage.model_validate(evidence_values())
    answer = RetrievalAnswer(
        evidence=evidence, introduction="This reporting names one organization."
    )
    restored = RetrievalAnswer.model_validate_json(answer.model_dump_json())
    assert restored.evidence.sources[0].citation.title == "Lobbying on AB 186"
    assert restored.evidence.sources[0].passages[0].text == "Disney lobbied for AB 186."
    assert (
        restored.evidence.execution.request.rewrite.assessment.explanation
        == "A complete lobbying register is unavailable."
    )
    assert restored.evidence.coverage.entries[0].collection_id == "calmatters"
    assert restored.evidence.context.omitted_passages == 2
    assert restored.evidence.failed_branches == ("structural",)
    assert restored.evidence.failure_disclosures == (
        "Graph connections matching the question could not be searched.",
    )


@pytest.mark.parametrize(
    "change",
    [
        "wrong_source",
        "duplicate_source",
        "wrong_span",
        "unverified",
        "budget_exceeded",
        "wrong_usage",
        "invented_candidate",
        "candidate_from_wrong_source",
    ],
)
def test_evidence_package_rejects_inconsistent_grounding_or_context_limits(change):
    values = evidence_values()
    if change == "wrong_source":
        values["sources"][0]["passages"][0]["source_article_id"] = "article-b"
    elif change == "duplicate_source":
        values["sources"].append(values["sources"][0])
    elif change == "wrong_span":
        values["sources"][0]["passages"][0]["end"] = 36
    elif change == "unverified":
        values["sources"][0]["passages"][0]["verification"] = "chunk_text"
    elif change == "budget_exceeded":
        values["context"]["limit"] = 24
    elif change == "wrong_usage":
        values["context"]["used"] = -1
    elif change == "invented_candidate":
        values["sources"][0]["passages"][0]["candidate"]["contributions"][0]["ranking"][
            "score"
        ] = 42
    elif change == "candidate_from_wrong_source":
        values["sources"][0]["passages"][0]["candidate"]["contributions"][0][
            "source_article_id"
        ] = "article-b"
    with pytest.raises(ValidationError):
        EvidencePackage.model_validate(values)


def test_empty_evidence_keeps_all_failed_branches_and_separate_assembly_failure():
    values = evidence_values()
    values["execution"]["outcomes"] = [
        {"branch": branch, "status": "failed"}
        for branch in ("full_text", "dense", "structural")
    ]
    values["sources"] = []
    values["context"]["used"] = 90
    package = EvidencePackage.model_validate(values)
    assert package.failure_disclosures == (
        "Graph connections matching the question could not be searched.",
        "Full-text retrieval could not be completed.",
        "Dense retrieval could not be completed.",
    )
    assert package.execution.request.rewrite.assessment.status == "deferred"
    assembly_failure = EvidenceAssemblyFailure(execution=package.execution)
    assert assembly_failure.outcome == "assembly_failed"
    assert assembly_failure.execution.failed_branches == (
        "full_text",
        "dense",
        "structural",
    )
    with pytest.raises(ValidationError):
        EvidencePackage.model_validate(assembly_failure.model_dump())


def test_answer_can_highlight_disagreement_with_typed_source_references():
    values = evidence_values()
    second = {
        "citation": {
            "source_article_id": "article-b",
            "title": "A different account",
            "url": "https://example.org/article-b",
        },
        "passages": [
            {
                "source_article_id": "article-b",
                "text": "Disney opposed AB 186.",
                "start": 0,
                "end": 22,
                "verification": "original_story",
                "candidate": {
                    "chunk_id": "article-b#chunk_0",
                    "rank": 2,
                    "fusion_score": 0.02,
                    "contributions": [
                        candidate_values(chunk_id="article-b#chunk_0", rank=2)
                    ],
                },
            }
        ],
    }
    values["sources"].append(second)
    values["context"]["used"] = 180
    values["execution"]["outcomes"][0]["candidates"].append(
        candidate_values(chunk_id="article-b#chunk_0", rank=2)
    )
    answer_values = {
        "evidence": values,
        "source_notes": [
            {
                "source_article_id": "article-a",
                "note": "Identifies a reported lobbying position.",
            }
        ],
        "disagreements": [
            {
                "source_article_ids": ["article-a", "article-b"],
                "description": "These sources report different positions.",
            }
        ],
    }
    answer = RetrievalAnswer.model_validate(answer_values)
    assert answer.disagreements[0].source_article_ids == ("article-a", "article-b")
    assert answer.evidence.sources[1].citation.published_date is None
    answer_values["disagreements"][0]["source_article_ids"] = ["article-a", "missing"]
    with pytest.raises(ValidationError):
        RetrievalAnswer.model_validate(answer_values)


def test_evidence_can_attach_monthly_detail_only_for_a_relevant_collection():
    values = evidence_values()
    values["monthly_coverage"] = [
        {
            "collection_id": "calmatters",
            "month": "2026-07",
            "availability": {"available_count": 40},
        }
    ]
    package = EvidencePackage.model_validate(values)
    assert package.monthly_coverage[0].availability.percentage is None
    values["monthly_coverage"][0]["collection_id"] = "unrelated"
    with pytest.raises(ValidationError):
        EvidencePackage.model_validate(values)


def test_assembly_preserves_all_routes_and_article_level_claims_for_a_passage():
    values = evidence_values()
    structural = candidate_values("structural")
    structural["routes"][0]["graph_claims"] = [
        {
            "source": {"id": "article-a", "label": "NewsArticle"},
            "target": {"id": "housing", "label": "PolicyArea"},
            "relationship_type": "DISCUSSES_TOPIC",
            "claim_key": {},
            "source_article_ids": ["article-a"],
            "chunk_ids": [],
        }
    ]
    values["execution"]["outcomes"][2] = {
        "branch": "structural",
        "status": "succeeded",
        "candidates": [structural],
    }
    with pytest.raises(ValidationError, match="every recorded candidate contribution"):
        EvidencePackage.model_validate(values)
    values["sources"][0]["passages"][0]["candidate"]["contributions"].append(structural)
    package = EvidencePackage.model_validate(values)
    routes = package.sources[0].passages[0].candidate.contributions
    assert routes[1].routes[0].graph_claims[0].source_article_ids == ("article-a",)
    assert package.failed_branches == ()


def test_context_limit_records_the_assemblers_token_accounting():
    values = evidence_values()
    values["context"] = {
        "unit": "tokens",
        "limit": 200,
        "used": 120,
        "max_passages": 10,
        "omitted_passages": 2,
    }
    package = EvidencePackage.model_validate(values)
    assert package.context.unit == "tokens" and package.context.used == 120
    values["context"]["used"] = 201
    with pytest.raises(ValidationError):
        EvidencePackage.model_validate(values)
