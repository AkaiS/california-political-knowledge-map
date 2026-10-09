"""Explicit publication limits through the persisted Source Guide HTTP boundary."""

import pytest
from test_chat_web import guide_client, stored_article, submit_guide
from test_retrieval import Branch, candidate

from knowledge_map.adapters.sqlite_db import init_db, save_story
from knowledge_map.schemas.retrieval import (
    GroundingEvidence,
    RetrievalBranch,
    SourceArticleCitation,
)
from knowledge_map.schemas.stories import Story

QUESTION = (
    "Only show articles published from January 1, 2023 through December 31, 2024 "
    "about California Proposition 1 mental health funding. Put those articles "
    "in oldest-to-newest publication order."
)
PASSAGE = "Proposition 1 mental health funding changed in 2023 and 2024."


def test_publication_bounds_omit_later_articles_groups_and_highlights_after_restart(
    tmp_path,
):
    db_path = tmp_path / "guides.db"
    init_db(str(db_path))
    notes = [
        {
            "source_article_id": f"https://example.com/{slug}",
            "note": "Read the Proposition 1 mental health funding section.",
        }
        for slug in ("dense", "full_text")
    ]
    for note in notes:
        save_story(
            Story(
                url=note["source_article_id"],
                title="Proposition 1 funding",
                content=PASSAGE,
            ),
            str(db_path),
        )

    async def article(candidate):
        evidence = await stored_article(candidate)
        if candidate.chunk_id == "dense":
            evidence = evidence.model_copy(
                update={
                    "citation": evidence.citation.model_copy(
                        update={"published_date": "2026-08-21T12:00:00Z"}
                    )
                }
            )
        return evidence.model_copy(update={"text": PASSAGE})

    with guide_client(
        db_path=db_path,
        assessment={
            "status": "deferred",
            "explanation": "The collection starts on June 15, 2023.",
            "recoverable_portion": "Articles published through December 31, 2024.",
            "reading_order": "publication_asc",
            "publication_date_from": "2023-01-01",
            "publication_date_through": "2024-12-31",
        },
        guidance={
            "source_notes": notes,
            "groups": [
                {
                    "kind": "timeline",
                    "label": "Publication timeline",
                    "order": "publication_asc",
                    "members": [
                        {
                            "source_article_id": note["source_article_id"],
                            "reading_direction": note["note"],
                        }
                        for note in notes
                    ],
                }
            ],
        },
        load_grounding=article,
    ) as (client, _, _):
        response = submit_guide(client, json={"question": QUESTION})
        guide = response.json()
        assert guide["status"] == "completed"
        assert guide["question"] == QUESTION
        assert [
            item["citation"]["source_article_id"] for item in guide["articles"]
        ] == ["https://example.com/full_text"]
        assert guide["relevance_order"] == ["https://example.com/full_text"]
        assert guide["groups"][0]["members"] == [
            {
                "source_article_id": "https://example.com/full_text",
                "reading_direction": notes[1]["note"],
            }
        ]
        assert guide["articles"][0]["section_links"]
        assert "https://example.com/dense" not in response.text
        assert PASSAGE not in response.text
    with guide_client(
        db_path=db_path, assessment=RuntimeError("Model unavailable after restart")
    ) as (client, prompts, _):
        assert client.get(f"/api/guides/{guide['guide_id']}").json() == guide
        assert prompts == []


def publication_sources(dates, branch=RetrievalBranch.DENSE):
    branches = {item: Branch(item, candidates=()) for item in RetrievalBranch}
    branches[branch] = Branch(
        branch,
        candidates=tuple(
            candidate(branch, slug, rank) for rank, slug in enumerate(dates, start=1)
        ),
    )

    async def article(item):
        return GroundingEvidence(
            chunk_id=item.chunk_id,
            text=PASSAGE,
            citation=SourceArticleCitation(
                source_article_id=item.source_article_id,
                url=item.source_article_id,
                title="Proposition 1 funding",
                published_date=dates[item.chunk_id],
            ),
        )

    return {
        "branches": branches,
        "load_grounding": article,
        "guidance": {
            "source_notes": [
                {
                    "source_article_id": f"https://example.com/{slug}",
                    "note": "Read the Proposition 1 mental health funding section.",
                }
                for slug in dates
            ]
        },
    }


@pytest.mark.parametrize("status", ["allowed", "deferred"])
@pytest.mark.parametrize("branch", list(RetrievalBranch))
def test_inclusive_publication_days_apply_to_every_branch_and_assessment(
    tmp_path, status, branch
):
    assessment = {
        "status": status,
        "publication_date_from": "2023-01-01",
        "publication_date_through": "2024-12-31",
    }
    if status == "deferred":
        assessment.update(
            explanation="Complete coverage is unavailable.",
            recoverable_portion="The available reporting may help.",
        )
    with guide_client(
        db_path=tmp_path / "guides.db",
        assessment=assessment,
        **publication_sources(
            {
                "too_early": "2022-12-31T23:59:59-08:00",
                "first_day": "2023-01-01",
                "last_day": "2024-12-31T23:59:59-08:00",
                "too_late": "2025-01-01T00:00:00+14:00",
                "missing": None,
                "invalid": "2024-02-30",
                "partial": "2024-12",
            },
            branch,
        ),
    ) as (client, _, _):
        guide = submit_guide(client, json={"question": QUESTION}).json()
    assert guide["status"] == "completed"
    assert [
        article["citation"]["source_article_id"] for article in guide["articles"]
    ] == [
        "https://example.com/first_day",
        "https://example.com/last_day",
    ]
    assert guide["assessment"]["publication_date_from"] == "2023-01-01"
    assert guide["assessment"]["publication_date_through"] == "2024-12-31"


@pytest.mark.parametrize(
    "bound, value, question, expected",
    [
        (
            "publication_date_from",
            "2024-01-01",
            "Only show reporting about Proposition 1 published on or after January 1, 2024.",
            ["https://example.com/newer"],
        ),
        (
            "publication_date_through",
            "2024-12-31",
            "Only show reporting about Proposition 1 published through December 31, 2024.",
            ["https://example.com/older"],
        ),
    ],
)
def test_one_sided_publication_limit_keeps_the_unbounded_end_open(
    tmp_path, bound, value, question, expected
):
    with guide_client(
        db_path=tmp_path / "guides.db",
        assessment={"status": "allowed", bound: value},
        **publication_sources(
            {"older": "2023-01-01", "newer": "2026-08-21T12:00:00Z", "missing": None}
        ),
    ) as (client, _, _):
        guide = submit_guide(client, json={"question": question}).json()
    assert guide["status"] == "completed"
    assert [
        article["citation"]["source_article_id"] for article in guide["articles"]
    ] == expected


def test_event_years_and_coverage_prose_do_not_restrict_publication_dates(tmp_path):
    with guide_client(
        db_path=tmp_path / "guides.db",
        assessment={
            "status": "deferred",
            "explanation": "Coverage of the requested events is incomplete.",
            "recoverable_portion": "Reporting on developments in 2023 and 2024.",
            "reading_order": "event_asc",
        },
        **publication_sources({"later_reporting": "2026-08-21", "undated": None}),
    ) as (client, _, _):
        guide = submit_guide(
            client,
            json={
                "question": "Where can I read about Proposition 1 developments in 2023 and 2024, in event order?"
            },
        ).json()
    assert guide["status"] == "completed"
    assert [
        article["citation"]["source_article_id"] for article in guide["articles"]
    ] == [
        "https://example.com/later_reporting",
        "https://example.com/undated",
    ]


def test_publication_bound_rejection_is_an_empty_guide_not_guidance_failure(tmp_path):
    with guide_client(
        db_path=tmp_path / "guides.db",
        assessment={
            "status": "allowed",
            "publication_date_from": "2023-01-01",
            "publication_date_through": "2024-12-31",
        },
        **publication_sources({"later_reporting": "2026-08-21T12:00:00Z"}),
    ) as (client, _, _):
        guide = submit_guide(client, json={"question": QUESTION}).json()
    assert guide["status"] == "empty"
    assert guide["articles"] == []
    assert guide["groups"] == []
    assert guide["latest_attempt"]["status"] == "empty"
    assert guide["search_details"]["completion"] == "completed"
    assert guide["disclosures"][0]["kind"] == "irrelevant_candidates"


@pytest.mark.parametrize(
    "first, last", [("2025-01-01", "2024-12-31"), ("2024-02-30", "2024-12-31")]
)
def test_invalid_assessed_publication_bounds_fail_assessment(tmp_path, first, last):
    with guide_client(
        db_path=tmp_path / "guides.db",
        assessment={
            "status": "allowed",
            "publication_date_from": first,
            "publication_date_through": last,
        },
    ) as (client, _, _):
        guide = submit_guide(client, json={"question": QUESTION}).json()
    assert guide["status"] == "assessment_failed"
    assert guide["articles"] == []
