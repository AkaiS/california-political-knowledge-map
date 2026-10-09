"""Verified original Story navigation through the saved-guide HTTP boundary."""

import pytest
from pydantic import HttpUrl
from test_chat_web import guide_client, stored_article, submit_guide

from knowledge_map.adapters.sqlite_db import init_db, replace_story, save_story
from knowledge_map.schemas.stories import Story

ARTICLE = "https://example.com/dense"
PASSAGE = "The committee heard testimony about housing eligibility."
NOTE = {"source_article_id": ARTICLE, "note": "Read the hearing on eligibility."}


def test_verified_original_section_and_ordinary_url_survive_restart(tmp_path):
    db_path = tmp_path / "guides.db"
    init_db(str(db_path))
    save_story(
        Story(
            url=ARTICLE,
            title="Hearing coverage",
            content=f"Introduction. {PASSAGE} Closing.",
        ),
        str(db_path),
    )

    async def grounding(candidate):
        evidence = await stored_article(candidate)
        return evidence.model_copy(update={"text": PASSAGE})

    with guide_client(
        db_path=db_path, guidance={"source_notes": [NOTE]}, load_grounding=grounding
    ) as (client, _, _):
        response = submit_guide(
            client, json={"question": "Where can I read about housing eligibility?"}
        )
        guide = response.json()
        assert guide["status"] == "completed"
        assert guide["articles"][0]["citation"]["url"] == ARTICLE
        assert guide["articles"][0]["section_links"] == [
            "https://example.com/dense#:~:text=The%20committee%20heard%20testimony%20about%20housing%20eligibility."
        ]
        assert PASSAGE not in response.text

    replace_story(
        Story(
            url=ARTICLE,
            title="Changed since retrieval",
            content="The original target is gone.",
        ),
        str(db_path),
    )

    async def unavailable(candidate):
        raise AssertionError("Reopening must not hydrate source evidence")

    with guide_client(
        db_path=db_path,
        assessment=RuntimeError("Model unavailable after restart"),
        load_grounding=unavailable,
    ) as (client, prompts, _):
        assert client.get(f"/api/guides/{guide['guide_id']}").json() == guide
        assert prompts == []


def test_compact_highlight_uses_original_context_to_disambiguate_repeated_wording(
    tmp_path,
):
    db_path = tmp_path / "guides.db"
    init_db(str(db_path))
    selected = f"{PASSAGE} Supporters questioned the income threshold."
    save_story(
        Story(
            url=ARTICLE,
            title="Hearing coverage",
            content=f"{PASSAGE} Opponents questioned the local costs. {selected}",
        ),
        str(db_path),
    )

    async def grounding(candidate):
        return (await stored_article(candidate)).model_copy(update={"text": selected})

    with guide_client(
        db_path=db_path, guidance={"source_notes": [NOTE]}, load_grounding=grounding
    ) as (client, _, _):
        guide = submit_guide(
            client, json={"question": "Where can I read about housing eligibility?"}
        ).json()
    assert guide["articles"][0]["section_links"] == [
        "https://example.com/dense#:~:text=The%20committee%20heard%20testimony%20about%20housing%20eligibility.,-Supporters%20questioned%20the%20income%20threshold."
    ]


@pytest.mark.parametrize(
    "original, selected",
    [
        (
            "She questioned the housing eligibility rules.",
            "Senator Smith questioned the housing eligibility rules. PRIVATE_CHUNK_SENTINEL",
        ),
        (f"{PASSAGE} Elsewhere. {PASSAGE}", PASSAGE),
        (f"{PASSAGE} Elsewhere. {PASSAGE.upper()}", PASSAGE),
        (f"{PASSAGE} Elsewhere. {PASSAGE.replace(' ', chr(10))}", PASSAGE),
        (None, PASSAGE),
        ("   ", "   "),
        ("Unrelated original reporting.", "PRIVATE_CHUNK_SENTINEL"),
    ],
)
def test_uncertain_original_location_preserves_ordinary_link_without_section_or_chunk_preview(
    tmp_path, original, selected
):
    db_path = tmp_path / "guides.db"
    init_db(str(db_path))
    if original is not None:
        save_story(
            Story(url=ARTICLE, title="Hearing coverage", content=original), str(db_path)
        )

    async def grounding(candidate):
        return (await stored_article(candidate)).model_copy(update={"text": selected})

    with guide_client(
        db_path=db_path, guidance={"source_notes": [NOTE]}, load_grounding=grounding
    ) as (client, _, _):
        response = submit_guide(
            client, json={"question": "Where can I read about eligibility?"}
        )
        guide = response.json()
        assert guide["status"] == "completed"
        assert guide["articles"][0]["citation"]["url"] == ARTICLE
        assert guide["articles"][0]["section_links"] == []
        assert "PRIVATE_CHUNK_SENTINEL" not in response.text
        assert "passages" not in response.text
        assert "chunk_id" not in response.text


def test_existing_fragment_keeps_ordinary_anchor_and_encodes_only_verified_highlight_text(
    tmp_path,
):
    db_path = tmp_path / "guides.db"
    init_db(str(db_path))
    selected = "Tenant-led groups asked about AB 1, rent & eligibility."
    save_story(
        Story(url=ARTICLE, title="Hearing coverage", content=selected), str(db_path)
    )

    async def grounding(candidate):
        evidence = await stored_article(candidate)
        return evidence.model_copy(
            update={
                "text": selected,
                "citation": evidence.citation.model_copy(
                    update={
                        "url": HttpUrl(ARTICLE + "#report:~:text=UNVERIFIED_OLD_TARGET")
                    }
                ),
            }
        )

    with guide_client(
        db_path=db_path, guidance={"source_notes": [NOTE]}, load_grounding=grounding
    ) as (client, _, _):
        response = submit_guide(
            client, json={"question": "Where can I read about housing eligibility?"}
        )
    article = response.json()["articles"][0]
    assert article["citation"]["url"] == ARTICLE + "#report"
    assert article["section_links"] == [
        "https://example.com/dense#report:~:text=Tenant%2Dled%20groups%20asked%20about%20AB%201%2C%20rent%20%26%20eligibility."
    ]
    assert "UNVERIFIED_OLD_TARGET" not in response.text


def test_verified_text_from_one_story_cannot_target_a_different_article_url(tmp_path):
    db_path = tmp_path / "guides.db"
    init_db(str(db_path))
    save_story(
        Story(url=ARTICLE, title="Hearing coverage", content=PASSAGE), str(db_path)
    )

    async def grounding(candidate):
        evidence = await stored_article(candidate)
        return evidence.model_copy(
            update={
                "text": PASSAGE,
                "citation": evidence.citation.model_copy(
                    update={"url": HttpUrl("https://other.example/report")}
                ),
            }
        )

    with guide_client(
        db_path=db_path, guidance={"source_notes": [NOTE]}, load_grounding=grounding
    ) as (client, _, _):
        guide = submit_guide(
            client, json={"question": "Where can I read about eligibility?"}
        ).json()
    assert guide["status"] == "completed"
    assert guide["articles"][0]["citation"]["url"] == "https://other.example/report"
    assert guide["articles"][0]["section_links"] == []


@pytest.mark.parametrize(
    "original, selected, url",
    [
        (
            "The organization supported housing eligibility.",
            "ation supported housing eligibility.",
            ARTICLE,
        ),
        ("x" * 200, "x" * 200, ARTICLE),
        (PASSAGE, PASSAGE, "https://example.com/" + "x" * 2040),
    ],
)
def test_unusable_word_boundary_or_overlong_target_falls_back_without_stranding_search(
    tmp_path, original, selected, url
):
    db_path = tmp_path / "guides.db"
    init_db(str(db_path))
    save_story(Story(url=url, title="Hearing coverage", content=original), str(db_path))
    from test_retrieval import Branch, candidate

    from knowledge_map.schemas.retrieval import RetrievalBranch

    branches = {
        branch: Branch(
            branch,
            (candidate(branch, "dense").model_copy(update={"source_article_id": url}),),
        )
        for branch in RetrievalBranch
    }

    async def grounding(candidate):
        return (await stored_article(candidate)).model_copy(update={"text": selected})

    with guide_client(
        db_path=db_path,
        branches=branches,
        guidance={"source_notes": [{"source_article_id": url, "note": NOTE["note"]}]},
        load_grounding=grounding,
    ) as (client, _, _):
        guide = submit_guide(
            client, json={"question": "Where can I read about eligibility?"}
        ).json()
    assert guide["status"] == "completed"
    assert guide["articles"][0]["citation"]["url"] == url
    assert guide["articles"][0]["section_links"] == []


def test_multiple_original_sections_stay_with_one_included_article_and_omitted_sources_stay_private(
    tmp_path,
):
    from test_retrieval import Branch, candidate

    from knowledge_map.schemas.retrieval import (
        GroundingEvidence,
        RetrievalBranch,
        SourceArticleCitation,
    )

    db_path = tmp_path / "guides.db"
    init_db(str(db_path))
    second = "Renters asked about the household income threshold."
    save_story(
        Story(url=ARTICLE, title="Hearing coverage", content=f"{PASSAGE} {second}"),
        str(db_path),
    )
    omitted = "https://example.com/omitted"
    save_story(
        Story(url=omitted, title="Omitted story", content="PRIVATE_CHUNK_SENTINEL"),
        str(db_path),
    )
    chunks = {
        "first": (ARTICLE, PASSAGE),
        "second": (ARTICLE, second),
        "duplicate": (ARTICLE, PASSAGE),
        "excluded": (omitted, "PRIVATE_CHUNK_SENTINEL"),
    }
    branches = {
        branch: Branch(
            branch,
            tuple(
                candidate(branch, name, index + 1).model_copy(
                    update={"source_article_id": url}
                )
                for index, (name, (url, _)) in enumerate(chunks.items())
            ),
        )
        for branch in RetrievalBranch
    }

    async def grounding(candidate):
        url, text = chunks[candidate.chunk_id]
        return GroundingEvidence(
            chunk_id=candidate.chunk_id,
            text=text,
            citation=SourceArticleCitation(
                source_article_id=url, title="Hearing coverage", url=url
            ),
        )

    groups = [
        {
            "kind": "contrast",
            "label": "Investigate concerns",
            "members": [
                {
                    "source_article_id": ARTICLE,
                    "reading_direction": "Read the eligibility discussion.",
                },
                {
                    "source_article_id": omitted,
                    "reading_direction": "PRIVATE_OMITTED_DIRECTION",
                },
            ],
        }
    ]
    with guide_client(
        db_path=db_path,
        branches=branches,
        guidance={"source_notes": [NOTE], "groups": groups},
        load_grounding=grounding,
    ) as (client, _, _):
        response = submit_guide(
            client, json={"question": "Where can I read about housing eligibility?"}
        )
        guide = response.json()
    assert guide["status"] == "completed"
    assert len(guide["articles"]) == 1
    assert guide["articles"][0]["section_links"] == [
        "https://example.com/dense#:~:text=The%20committee%20heard%20testimony%20about%20housing%20eligibility.",
        "https://example.com/dense#:~:text=Renters%20asked%20about%20the%20household%20income%20threshold.",
    ]
    assert guide["groups"][0]["members"] == [groups[0]["members"][0]]
    for hidden in ("PRIVATE_", "omitted", "passages", "chunk_id"):
        assert hidden not in response.text


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///private/source",
    ],
)
def test_unsafe_source_urls_cannot_create_ordinary_or_section_links(
    tmp_path, unsafe_url
):
    from knowledge_map.schemas.retrieval import GroundingEvidence, SourceArticleCitation

    async def grounding(candidate):
        return GroundingEvidence(
            chunk_id=candidate.chunk_id,
            text=PASSAGE,
            citation=SourceArticleCitation(
                source_article_id=candidate.source_article_id,
                title="Unsafe source",
                url=unsafe_url,
            ),
        )

    with guide_client(
        db_path=tmp_path / "guides.db",
        guidance={"source_notes": [NOTE]},
        load_grounding=grounding,
    ) as (client, _, _):
        response = submit_guide(
            client, json={"question": "Where can I read about housing eligibility?"}
        )
    assert response.json()["status"] == "assembly_failed"
    assert response.json()["articles"] == []
    assert unsafe_url not in response.text
