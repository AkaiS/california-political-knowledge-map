"""Evidence Assembly decisions saved through chat and inspected by the CLI."""

import json

import pytest
from test_chat_audit_retrieval import answer_question, retrieval_chat
from test_retrieval import COVERAGE, Branch, candidate, load_grounding

from knowledge_map.core.evidence import EvidenceHydrationError
from knowledge_map.schemas.evidence import EvidenceContextLimits
from knowledge_map.schemas.retrieval import (
    CoverageDescription,
    GroundingEvidence,
    MonthlyCoverage,
    RetrievalBranch,
)


def test_assembly_saves_selected_ids_relevant_coverage_and_measured_context(tmp_path):
    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    unrelated = COVERAGE.entries[0].model_copy(
        update={"collection_id": "unrelated", "description": "Unrelated coverage."}
    )
    with retrieval_chat(
        tmp_path,
        branches,
        coverage=CoverageDescription(entries=(unrelated, *COVERAGE.entries)),
        monthly_coverage=(
            MonthlyCoverage(
                collection_id="reporting",
                month="2026-09",
                availability={"available_count": 2},
            ),
            MonthlyCoverage(
                collection_id="unrelated",
                month="2026-09",
                availability={"available_count": 99},
            ),
        ),
    ) as (client, read_trail, guidance):
        response = answer_question(client)
        records = read_trail()

    (assembly,) = (record for record in records if record.name == "evidence_assembly")
    assert assembly.status == "succeeded"
    assert assembly.metadata == {
        "selected_chunk_ids": ["structural", "dense", "full_text"],
        "omitted_candidates": [],
        "context": {
            "unit": "characters",
            "limit": 24000,
            "used": len(
                json.dumps(
                    guidance[0],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
            "max_passages": 12,
            "omitted_passages": 0,
        },
        "coverage": guidance[0]["coverage"],
        "monthly_coverage": [
            {
                "collection_id": "reporting",
                "month": "2026-09",
                "availability": {"available_count": 2, "expected_count": None},
            }
        ],
    }
    assert [
        entry["collection_id"] for entry in assembly.metadata["coverage"]["entries"]
    ] == ["reporting"]
    assert len({record.session_id for record in records}) == 1
    assert len({record.stage_id for record in records}) == len(records)
    (fusion,) = (record for record in records if record.name == "fusion")
    assert fusion.ended_at <= assembly.started_at <= assembly.ended_at
    assert "The union supports AB 1." in response.text
    assert "The union supports AB 1." not in assembly.model_dump_json()
    assert "Unrelated coverage." not in assembly.model_dump_json()


def test_oversized_passage_does_not_hide_later_evidence_or_the_passage_limit(tmp_path):
    chunks = ["too-long", "a-first", "b-middle", "a-last", "after-limit"]
    branches = {branch: Branch(branch, ()) for branch in RetrievalBranch}
    branches[RetrievalBranch.FULL_TEXT] = Branch(
        RetrievalBranch.FULL_TEXT,
        tuple(
            candidate(RetrievalBranch.FULL_TEXT, chunk, rank).model_copy(
                update={"source_article_id": "https://example.com/shared"}
                if chunk.startswith("a-")
                else {}
            )
            for rank, chunk in enumerate(chunks, start=1)
        ),
    )

    async def stored_grounding(candidate):
        grounding = await load_grounding(candidate)
        return grounding.model_copy(
            update={
                "text": "Oversized wording. " * 1000
                if candidate.chunk_id == "too-long"
                else f"Stored wording for {candidate.chunk_id}."
            }
        )

    with retrieval_chat(
        tmp_path,
        branches,
        load_grounding=stored_grounding,
        context_limits=EvidenceContextLimits(character_limit=5000, max_passages=3),
    ) as (client, read_trail, guidance):
        response = answer_question(client)
        records = read_trail()

    (assembly,) = (record for record in records if record.name == "evidence_assembly")
    assert assembly.status == "succeeded"
    assert assembly.metadata["selected_chunk_ids"] == ["a-first", "b-middle", "a-last"]
    assert assembly.metadata["omitted_candidates"] == [
        {"chunk_id": "too-long", "reason": "character_limit"},
        {"chunk_id": "after-limit", "reason": "passage_limit"},
    ]
    context = assembly.metadata["context"]
    assert context["limit"] == 5000
    assert context["max_passages"] == 3
    assert context["omitted_passages"] == 2
    assert 0 < context["used"] <= 5000
    assert [
        [passage["candidate"]["chunk_id"] for passage in source["passages"]]
        for source in guidance[0]["sources"]
    ] == [["a-first", "a-last"], ["b-middle"]]
    for chunk in ("a-first", "b-middle", "a-last"):
        assert f"Stored wording for {chunk}." in response.text
    assert "Stored wording for after-limit." not in response.text
    assert "Oversized wording." not in response.text


@pytest.mark.parametrize(
    "error", [EvidenceHydrationError, LookupError, OSError, ValueError]
)
def test_hydration_failure_is_saved_without_exposing_candidate_wording(tmp_path, error):
    async def unavailable_grounding(candidate):
        raise error("PRIVATE_STORAGE_DIAGNOSTIC")

    unverified = candidate(RetrievalBranch.FULL_TEXT)
    unverified = unverified.model_copy(
        update={
            "grounding": GroundingEvidence(
                chunk_id=unverified.chunk_id,
                text="UNVERIFIED_CANDIDATE_WORDING",
                citation={
                    "source_article_id": unverified.source_article_id,
                    "title": "Candidate title",
                    "url": unverified.source_article_id,
                },
            )
        }
    )
    branches = {branch: Branch(branch, ()) for branch in RetrievalBranch}
    branches[RetrievalBranch.FULL_TEXT] = Branch(
        RetrievalBranch.FULL_TEXT, (unverified,)
    )
    with retrieval_chat(tmp_path, branches, load_grounding=unavailable_grounding) as (
        client,
        read_trail,
        guidance,
    ):
        response = answer_question(client)
        records = read_trail()

    (assembly,) = (record for record in records if record.name == "evidence_assembly")
    assert assembly.status == "failed"
    assert assembly.metadata == {
        "context": {"unit": "characters", "limit": 24000, "max_passages": 12},
        "failure_kind": "hydration",
        "diagnostic": "Grounding Evidence could not be assembled.",
    }
    assert all(
        record.status == "succeeded"
        for record in records
        if record.name
        in {"full_text_search", "dense_search", "structural_search", "fusion"}
    )

    assert guidance == []
    assert "Grounding Evidence could not be assembled." in response.text
    assert "PRIVATE_STORAGE_DIAGNOSTIC" not in response.text + "".join(
        record.model_dump_json() for record in records
    )
    assert "UNVERIFIED_CANDIDATE_WORDING" not in response.text + "".join(
        record.model_dump_json() for record in records
    )


def test_mandatory_context_over_budget_records_a_failed_assembly(tmp_path):
    branches = {branch: Branch(branch, ()) for branch in RetrievalBranch}
    with retrieval_chat(
        tmp_path,
        branches,
        context_limits=EvidenceContextLimits(character_limit=10),
    ) as (client, read_trail, guidance):
        response = answer_question(client)
        records = read_trail()

    (assembly,) = (record for record in records if record.name == "evidence_assembly")
    assert assembly.status == "failed"
    assert assembly.metadata == {
        "context": {"unit": "characters", "limit": 10, "max_passages": 12},
        "failure_kind": "budget",
        "diagnostic": "Grounding Evidence could not be assembled.",
    }
    assert guidance == []
    assert "Grounding Evidence could not be assembled." in response.text
    assert all(
        record.status == "succeeded"
        for record in records
        if record.name
        in {"full_text_search", "dense_search", "structural_search", "fusion"}
    )


@pytest.mark.parametrize("mismatch", ["chunk", "article", "citation"])
def test_provenance_failure_keeps_the_retrieval_results_and_withholds_passages(
    tmp_path, mismatch
):
    branches = {branch: Branch(branch, ()) for branch in RetrievalBranch}
    branches[RetrievalBranch.FULL_TEXT] = Branch(
        RetrievalBranch.FULL_TEXT,
        tuple(
            candidate(RetrievalBranch.FULL_TEXT, chunk, rank).model_copy(
                update={"source_article_id": "https://example.com/shared"}
            )
            for rank, chunk in enumerate(("first", "second"), start=1)
        ),
    )

    async def inconsistent_grounding(candidate):
        grounding = await load_grounding(candidate)
        if candidate.chunk_id == "second":
            if mismatch == "chunk":
                return grounding.model_copy(update={"chunk_id": "PRIVATE_WRONG_CHUNK"})
            field = "source_article_id" if mismatch == "article" else "title"
            return grounding.model_copy(
                update={
                    "citation": grounding.citation.model_copy(
                        update={field: "PRIVATE_WRONG_ARTICLE"}
                    )
                }
            )
        return grounding

    with retrieval_chat(tmp_path, branches, load_grounding=inconsistent_grounding) as (
        client,
        read_trail,
        guidance,
    ):
        response = answer_question(client)
        records = read_trail()

    (assembly,) = (record for record in records if record.name == "evidence_assembly")
    assert assembly.status == "failed"
    assert assembly.metadata["failure_kind"] == "provenance"
    assert (
        assembly.metadata["diagnostic"] == "Grounding Evidence could not be assembled."
    )
    assert guidance == []
    (search,) = (record for record in records if record.name == "full_text_search")
    assert search.status == "succeeded"
    assert search.metadata["returned_candidate_count"] == 2
    assert "Grounding Evidence could not be assembled." in response.text
    assert "The union supports AB 1." not in response.text + assembly.model_dump_json()
    assert "PRIVATE_" not in response.text + "".join(
        record.model_dump_json() for record in records
    )


@pytest.mark.parametrize("entries", [(), COVERAGE.entries * 2])
def test_missing_or_duplicate_relevant_coverage_is_a_safe_assembly_failure(
    tmp_path, entries
):
    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    with retrieval_chat(
        tmp_path, branches, coverage=CoverageDescription(entries=entries)
    ) as (client, read_trail, guidance):
        response = answer_question(client)
        records = read_trail()

    (assembly,) = (record for record in records if record.name == "evidence_assembly")
    assert assembly.status == "failed"
    assert assembly.metadata["failure_kind"] == "coverage"
    assert (
        assembly.metadata["diagnostic"] == "Grounding Evidence could not be assembled."
    )
    assert guidance == []
    assert "Grounding Evidence could not be assembled." in response.text
    assert "The union supports AB 1." not in response.text + assembly.model_dump_json()
    assert all(
        record.status == "succeeded"
        for record in records
        if record.name
        in {"full_text_search", "dense_search", "structural_search", "fusion"}
    )


@pytest.mark.parametrize("has_candidate", [False, True])
def test_zero_selected_passages_are_successful_with_the_actual_omissions(
    tmp_path, has_candidate
):
    branches = {branch: Branch(branch, ()) for branch in RetrievalBranch}
    if has_candidate:
        branches[RetrievalBranch.FULL_TEXT] = Branch(RetrievalBranch.FULL_TEXT)

    async def oversized_grounding(candidate):
        grounding = await load_grounding(candidate)
        return grounding.model_copy(update={"text": "Oversized wording. " * 1000})

    with retrieval_chat(
        tmp_path,
        branches,
        load_grounding=oversized_grounding,
        context_limits=EvidenceContextLimits(character_limit=2000),
    ) as (client, read_trail, guidance):
        response = answer_question(client)
        records = read_trail()

    (assembly,) = (record for record in records if record.name == "evidence_assembly")
    assert assembly.status == "succeeded"
    assert assembly.metadata["selected_chunk_ids"] == []
    assert assembly.metadata["omitted_candidates"] == (
        [{"chunk_id": "full_text", "reason": "character_limit"}]
        if has_candidate
        else []
    )
    assert assembly.metadata["context"]["omitted_passages"] == int(has_candidate)
    assert 0 < assembly.metadata["context"]["used"] <= 2000
    assert guidance[0]["sources"] == []
    assert "Consult the reporting." in response.text
    assert "Grounding Evidence could not be assembled." not in response.text


def test_deadline_during_assembly_is_recorded_without_changing_successful_branches(
    tmp_path,
):
    now = 0.0

    async def slow_grounding(candidate):
        nonlocal now
        grounding = await load_grounding(candidate)
        now = 1.0
        return grounding

    branches = {branch: Branch(branch) for branch in RetrievalBranch}
    with retrieval_chat(
        tmp_path,
        branches,
        load_grounding=slow_grounding,
        deadline_seconds=1,
        clock=lambda: now,
    ) as (client, read_trail, guidance):
        response = answer_question(client)
        records = read_trail()

    (assembly,) = (record for record in records if record.name == "evidence_assembly")
    assert assembly.status == "failed"
    assert assembly.metadata["failure_kind"] == "deadline_exhausted"
    assert assembly.metadata["diagnostic"] == (
        "Evidence Assembly could not finish within the retrieval deadline."
    )
    assert guidance == []
    assert "Grounding Evidence could not be assembled." in response.text
    assert "The union supports AB 1." not in response.text
    assert all(
        record.status == "succeeded"
        for record in records
        if record.name
        in {"full_text_search", "dense_search", "structural_search", "fusion"}
    )
