"""Chat Session outcomes become terminal Source Guides through one projection."""

import pytest

from knowledge_map.adapters.sqlite_db import (
    cache_scraped_html,
    init_db,
    register_publication,
    save_story,
)
from knowledge_map.chat_presentation import (
    ChatSessionStageFailure,
    StoppedAttempt,
    project_source_guide,
    render_source_guide,
)
from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.schemas.retrieval import EvidenceAssemblyFailure, RetrievalAnswer
from knowledge_map.schemas.stories import Story

QUESTION = "Where can I read about housing eligibility?"
ARTICLE = "https://example.com/hearing"
PASSAGE = "The committee heard testimony about housing eligibility."
BRANCHES = ("full_text", "dense", "structural")


def branch_candidate(branch):
    kind, field = {
        "full_text": ("chunk_text", "text"),
        "dense": ("chunk_embedding", "embedding"),
        "structural": ("typed_traversal", None),
    }[branch]
    return {
        "chunk_id": "hearing#0",
        "source_article_id": ARTICLE,
        "ranking": {"branch": branch, "rank": 1, "score": None},
        "routes": [
            {
                "kind": kind,
                "matched_field": field,
                "entry_node": {"id": "hearing#0", "label": "Chunk"},
            }
        ],
    }


def retrieval_answer(
    *,
    failed=(),
    selected=True,
    noted=True,
    assessment=None,
    unmatched=(),
):
    found = next((branch for branch in BRANCHES if branch not in failed), None)
    candidates = [branch_candidate(found)] if selected else []
    return RetrievalAnswer.model_validate(
        {
            "evidence": {
                "execution": {
                    "request": {
                        "rewrite": {
                            "question": QUESTION,
                            "relational": True,
                            "assessment": assessment or {"status": "allowed"},
                        }
                    },
                    "outcomes": [
                        {"branch": branch, "status": "failed"}
                        if branch in failed
                        else {
                            "branch": branch,
                            "status": "succeeded",
                            "candidates": candidates if branch == found else [],
                        }
                        for branch in BRANCHES
                    ],
                },
                "sources": [
                    {
                        "citation": {
                            "source_article_id": ARTICLE,
                            "title": "Hearing coverage",
                            "url": ARTICLE,
                            "published_date": "2026-07-01",
                        },
                        "passages": [
                            {
                                "source_article_id": ARTICLE,
                                "text": PASSAGE,
                                "provenance": "stored_chunk",
                                "candidate": {
                                    "chunk_id": "hearing#0",
                                    "rank": 1,
                                    "fusion_score": 0.03,
                                    "contributions": candidates,
                                },
                            }
                        ],
                    }
                ]
                if selected
                else [],
                "coverage": {
                    "entries": [
                        {
                            "collection_id": "calmatters",
                            "name": "CalMatters",
                            "kind": "publication",
                            "description": "Reporting on California politics.",
                            "availability": {"available_count": 98},
                            "date_basis": "publication_date",
                        }
                    ]
                },
                "context": {
                    "unit": "tokens",
                    "limit": 1000,
                    "max_passages": 10,
                    "used": 120,
                    "omitted_passages": 0,
                },
            },
            "source_notes": [
                {"source_article_id": ARTICLE, "note": "Read the hearing testimony."}
            ]
            if selected and noted
            else [],
            "unmatched_requests": list(unmatched),
        }
    )


def story_store(tmp_path, name="configured.db"):
    path = str(tmp_path / name)
    init_db(path)
    save_story(
        Story(
            url=ARTICLE,
            title="Hearing coverage",
            content=f"Introduction. {PASSAGE} Closing.",
        ),
        path,
    )
    register_publication(
        "calmatters", "CalMatters", "https://example.com", db_path=path
    )
    cache_scraped_html(ARTICLE, "calmatters", "<html></html>", db_path=path)
    return path


def test_completed_answer_reads_publication_and_highlight_from_the_named_store(
    tmp_path,
):
    guide = project_source_guide(
        retrieval_answer(),
        question=QUESTION,
        story_db_path=story_store(tmp_path),
    )

    assert guide.question == QUESTION
    assert guide.status == "completed"
    assert guide.message is None
    assert guide.disclosures == ()
    assert guide.partial is False
    assert guide.search_details.completion == "completed"
    assert guide.search_details.included_articles == 1
    assert [collection.name for collection in guide.search_details.collections] == [
        "CalMatters"
    ]
    [article] = guide.articles
    assert article.reading_direction == "Read the hearing testimony."
    assert article.publication == "CalMatters"
    assert [str(link) for link in article.section_links] == [
        "https://example.com/hearing#:~:text=The%20committee%20heard%20testimony%20about%20housing%20eligibility."
    ]


def test_assessed_candidates_without_reading_directions_are_an_empty_guide(tmp_path):
    guide = project_source_guide(
        retrieval_answer(noted=False),
        question=QUESTION,
        story_db_path=story_store(tmp_path),
    )

    assert guide.status == "empty"
    assert guide.articles == ()
    assert [d.kind for d in guide.disclosures] == ["irrelevant_candidates"]
    assert guide.message == (
        "Retrieved articles were assessed, but none supported a reading direction "
        "for this question. This does not establish that matching reporting does "
        "not exist."
    )
    assert guide.search_details.completion == "completed"


def test_search_without_candidates_discloses_no_matches(tmp_path):
    guide = project_source_guide(
        retrieval_answer(selected=False),
        question=QUESTION,
        story_db_path=story_store(tmp_path),
    )

    assert guide.status == "empty"
    assert [d.kind for d in guide.disclosures] == ["no_matches"]
    assert guide.message == (
        "No articles were available to assess within this search's limits. "
        "This does not establish that matching reporting does not exist."
    )


def test_partly_failed_search_keeps_available_reading_with_a_partial_disclosure(
    tmp_path,
):
    guide = project_source_guide(
        retrieval_answer(failed=("dense",)),
        question=QUESTION,
        story_db_path=story_store(tmp_path),
    )

    assert guide.status == "completed"
    assert guide.partial is True
    assert len(guide.articles) == 1
    assert [d.kind for d in guide.disclosures] == ["partial_search"]
    assert guide.message == (
        "Part of this search failed. Available reading is retained, but this "
        "search is incomplete."
    )
    assert guide.search_details.completion == "partial"


def test_search_whose_every_branch_failed_is_failed_rather_than_empty(tmp_path):
    guide = project_source_guide(
        retrieval_answer(failed=BRANCHES, selected=False),
        question=QUESTION,
        story_db_path=story_store(tmp_path),
    )

    assert guide.status == "retrieval_failed"
    assert guide.partial is True
    assert [d.kind for d in guide.disclosures] == ["retrieval_failed"]
    assert guide.message == (
        "The search failed before articles could be assessed. Choose Retry to "
        "search again."
    )
    assert guide.search_details.completion == "failed"


def test_evidence_assembly_failure_asks_the_reader_to_retry(tmp_path):
    failure = EvidenceAssemblyFailure(execution=retrieval_answer().evidence.execution)

    guide = project_source_guide(
        failure, question=QUESTION, story_db_path=story_store(tmp_path)
    )

    assert guide.question == QUESTION
    assert guide.status == "assembly_failed"
    assert guide.articles == ()
    assert [d.kind for d in guide.disclosures] == ["assembly_failed"]
    assert guide.message == (
        "Retrieved material could not be prepared for relevance review. Choose "
        "Retry to search again."
    )


def test_unmatched_parts_of_the_question_are_disclosed_with_their_portion(tmp_path):
    guide = project_source_guide(
        retrieval_answer(
            unmatched=(
                {
                    "request_portion": "the vote count",
                    "explanation": "No selected article reports the vote count.",
                },
            )
        ),
        question=QUESTION,
        story_db_path=story_store(tmp_path),
    )

    assert guide.status == "completed"
    [disclosure] = guide.disclosures
    assert disclosure.kind == "unmatched_request"
    assert disclosure.request_portion == "the vote count"
    assert disclosure.message == "No selected article reports the vote count."


def test_declined_question_explains_why_it_was_not_searched(tmp_path):
    assessment = QuestionAssessment(
        status="declined",
        explanation="Questions about a person's private motives are unsupported.",
    )

    guide = project_source_guide(
        assessment, question=QUESTION, story_db_path=str(tmp_path / "unused.db")
    )

    assert guide.question == QUESTION
    assert guide.status == "declined"
    assert guide.assessment == assessment
    assert (
        guide.message == "Questions about a person's private motives are unsupported."
    )
    assert [(d.kind, d.message) for d in guide.disclosures] == [
        ("declined", "Questions about a person's private motives are unsupported.")
    ]
    assert guide.articles == ()


def test_question_needing_an_edit_says_what_to_change(tmp_path):
    assessment = QuestionAssessment(
        status="needs_edit", explanation="Name the bill or measure you mean."
    )

    guide = project_source_guide(
        assessment, question=QUESTION, story_db_path=str(tmp_path / "unused.db")
    )

    assert guide.status == "needs_edit"
    assert guide.message == "Name the bill or measure you mean."
    assert [(d.kind, d.message) for d in guide.disclosures] == [
        ("needs_edit", "Name the bill or measure you mean.")
    ]


DEFERRED = {
    "status": "deferred",
    "explanation": "A complete lobbying register is not yet available.",
    "recoverable_portion": "Reporting may still name individual organizations.",
}
DEFERRED_MESSAGE = (
    "A complete lobbying register is not yet available.\n\n"
    "Reporting may still name individual organizations."
)


def test_deferred_explanation_stays_visible_after_a_completed_search(tmp_path):
    guide = project_source_guide(
        retrieval_answer(assessment=DEFERRED),
        question=QUESTION,
        story_db_path=story_store(tmp_path),
    )

    assert guide.status == "completed"
    assert guide.assessment.status == "deferred"
    assert [(d.kind, d.message) for d in guide.disclosures] == [
        ("deferred", DEFERRED_MESSAGE)
    ]
    assert guide.message == DEFERRED_MESSAGE


def test_deferred_explanation_follows_the_empty_search_disclosure(tmp_path):
    guide = project_source_guide(
        retrieval_answer(assessment=DEFERRED, selected=False),
        question=QUESTION,
        story_db_path=story_store(tmp_path),
    )

    assert guide.status == "empty"
    assert [d.kind for d in guide.disclosures] == ["no_matches", "deferred"]
    assert guide.message.endswith(DEFERRED_MESSAGE)


STAGE_FAILURES = {
    "assessment": (
        "assessment_failed",
        "The question could not be assessed. Choose Retry to search again.",
    ),
    "retrieval": (
        "retrieval_failed",
        "The search could not be completed. Choose Retry to search again.",
    ),
    "guidance": (
        "guidance_failed",
        (
            "Reading directions could not be prepared. The retrieved articles have "
            "not passed the relevance check. Choose Retry to search again."
        ),
    ),
}


@pytest.mark.parametrize("stage", STAGE_FAILURES)
def test_failure_at_a_chat_session_stage_offers_retry(tmp_path, stage):
    status, message = STAGE_FAILURES[stage]

    guide = project_source_guide(
        ChatSessionStageFailure(stage=stage),
        question=QUESTION,
        story_db_path=str(tmp_path / "unused.db"),
    )

    assert guide.question == QUESTION
    assert guide.status == status
    assert guide.assessment is None
    assert guide.message == message
    assert [(d.kind, d.message) for d in guide.disclosures] == [(status, message)]
    assert guide.articles == ()


@pytest.mark.parametrize("stage", STAGE_FAILURES)
def test_deferred_explanation_stays_visible_after_a_stage_failure(tmp_path, stage):
    status, message = STAGE_FAILURES[stage]
    assessment = QuestionAssessment.model_validate(DEFERRED)

    guide = project_source_guide(
        ChatSessionStageFailure(stage=stage, assessment=assessment),
        question=QUESTION,
        story_db_path=str(tmp_path / "unused.db"),
    )

    assert guide.status == status
    assert guide.assessment == assessment
    assert [(d.kind, d.message) for d in guide.disclosures] == [
        (status, message),
        ("deferred", DEFERRED_MESSAGE),
    ]
    assert guide.message == f"{message}\n\n{DEFERRED_MESSAGE}"


def test_cancelled_attempt_says_the_search_was_cancelled(tmp_path):
    guide = project_source_guide(
        StoppedAttempt(reason="cancelled"),
        question=QUESTION,
        story_db_path=str(tmp_path / "unused.db"),
    )

    assert guide.question == QUESTION
    assert guide.status == "cancelled"
    assert guide.message == "This search was cancelled."
    assert guide.disclosures == ()
    assert guide.articles == ()


def test_interrupted_attempt_says_the_search_did_not_finish(tmp_path):
    guide = project_source_guide(
        StoppedAttempt(reason="interrupted"),
        question=QUESTION,
        story_db_path=str(tmp_path / "unused.db"),
    )

    assert guide.status == "interrupted"
    assert guide.message == "This search was interrupted before it finished."
    assert guide.disclosures == ()
    assert guide.articles == ()


def test_attempt_that_exceeded_its_time_limit_offers_retry(tmp_path):
    guide = project_source_guide(
        StoppedAttempt(reason="exceeded_time_limit"),
        question=QUESTION,
        story_db_path=str(tmp_path / "unused.db"),
    )

    assert guide.status == "interrupted"
    assert (
        guide.message
        == "This search exceeded its time limit. Choose Retry to search again."
    )
    assert guide.disclosures == ()
    assert guide.articles == ()


def test_guide_shows_the_question_the_caller_submitted(tmp_path):
    guide = project_source_guide(
        retrieval_answer(),
        question="Which housing hearings covered eligibility?",
        story_db_path=story_store(tmp_path),
    )

    assert guide.question == "Which housing hearings covered eligibility?"


def test_projection_never_consults_a_store_other_than_the_named_one(tmp_path):
    story_store(tmp_path, "document_store.db")
    elsewhere = str(tmp_path / "other.db")
    init_db(elsewhere)

    guide = project_source_guide(
        retrieval_answer(), question=QUESTION, story_db_path=elsewhere
    )

    [article] = guide.articles
    assert article.publication is None
    assert article.section_links == ()


def test_rendering_presents_the_projected_guide_with_its_highlights(tmp_path):
    guide = project_source_guide(
        retrieval_answer(failed=("dense",)),
        question=QUESTION,
        story_db_path=story_store(tmp_path),
    )

    assert render_source_guide(guide) == (
        f"{QUESTION}\n\n"
        "Part of this search failed. Available reading is retained, but this "
        "search is incomplete.\n\n"
        "1. [Hearing coverage](<https://example.com/hearing>)\n\n"
        "CalMatters\n\n"
        "2026-07-01\n\n"
        "Read the hearing testimony.\n\n"
        "   - [Relevant highlight 1](<https://example.com/hearing#:~:text="
        "The%20committee%20heard%20testimony%20about%20housing%20eligibility.>)"
    )
