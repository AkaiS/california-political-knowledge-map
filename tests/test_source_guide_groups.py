"""Question-specific reading views through the saved-guide HTTP boundary."""

import pytest
from test_chat_web import guide_client, stored_article, submit_guide

NOTES = [
    {
        "source_article_id": "https://example.com/dense",
        "note": "Read the hearing coverage to investigate the housing debate.",
    },
    {
        "source_article_id": "https://example.com/full_text",
        "note": "Read the proposal coverage to investigate eligibility.",
    },
]


def test_contrast_groups_keep_distinct_overlapping_directions_and_only_included_articles_after_restart(
    tmp_path,
):
    db_path = tmp_path / "guides.db"
    groups = [
        {
            "kind": "contrast",
            "label": "Investigate supporters' arguments",
            "members": [
                {
                    "source_article_id": "https://example.com/dense",
                    "reading_direction": "Read the hearing's supporters section.",
                },
                {
                    "source_article_id": "https://example.com/structural",
                    "reading_direction": "EXCLUDED_ARTICLE_DIRECTION",
                },
                {
                    "source_article_id": "https://example.com/invented",
                    "reading_direction": "UNKNOWN_ARTICLE_DIRECTION",
                },
            ],
        },
        {
            "kind": "contrast",
            "label": "Investigate detractors' arguments",
            "members": [
                {
                    "source_article_id": "https://example.com/dense",
                    "reading_direction": "Read the hearing's detractors section.",
                }
            ],
        },
    ]
    with guide_client(
        db_path=db_path,
        guidance={"source_notes": NOTES, "groups": groups},
        load_grounding=stored_article,
    ) as (client, _, _):
        response = submit_guide(
            client,
            json={"question": "Where can I read supporters and detractors of AB 1?"},
        )
        guide = response.json()
        assert guide["status"] == "completed"
        assert [
            article["citation"]["source_article_id"] for article in guide["articles"]
        ] == ["https://example.com/dense", "https://example.com/full_text"]
        assert [group["label"] for group in guide["groups"]] == [
            "Investigate supporters' arguments",
            "Investigate detractors' arguments",
        ]
        assert [group["members"] for group in guide["groups"]] == [
            [
                {
                    "source_article_id": "https://example.com/dense",
                    "reading_direction": "Read the hearing's supporters section.",
                }
            ],
            [
                {
                    "source_article_id": "https://example.com/dense",
                    "reading_direction": "Read the hearing's detractors section.",
                }
            ],
        ]
    with guide_client(
        db_path=db_path, assessment=RuntimeError("Model unavailable after restart")
    ) as (client, prompts, _):
        restored = client.get(f"/api/guides/{guide['guide_id']}")
        assert restored.json() == guide
        assert (
            client.get("/api/guides").json()["guides"][0]["guide_id"]
            == guide["guide_id"]
        )
        assert prompts == []
        for hidden in (
            "PRIVATE_CHUNK_SENTINEL",
            "EXCLUDED_ARTICLE_DIRECTION",
            "UNKNOWN_ARTICLE_DIRECTION",
            "passages",
            "chunk_id",
        ):
            assert hidden not in restored.text


def test_publication_timeline_sorts_stored_dates_and_keeps_relevance_order_available(
    tmp_path,
):
    notes = [
        {
            "source_article_id": "https://example.com/structural",
            "note": "Read the undated budget coverage.",
        },
        *NOTES,
    ]
    with guide_client(
        db_path=tmp_path / "guides.db",
        assessment={"status": "allowed", "reading_order": "publication_asc"},
        guidance={
            "source_notes": notes,
            "groups": [
                {
                    "kind": "timeline",
                    "label": "Read reporting in publication order",
                    "order": "publication_desc",
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
        load_grounding=stored_article,
    ) as (client, _, _):
        guide = submit_guide(
            client, json={"question": "Read AB 1 reporting oldest publication first."}
        ).json()
    assert guide["status"] == "completed"
    assert guide["relevance_order"] == [
        "https://example.com/structural",
        "https://example.com/dense",
        "https://example.com/full_text",
    ]
    timeline = guide["groups"][0]
    assert timeline["order"] == "publication_asc"
    assert [member["source_article_id"] for member in timeline["members"]] == [
        "https://example.com/full_text",
        "https://example.com/dense",
        "https://example.com/structural",
    ]
    assert "published_date" not in guide["articles"][-1]["citation"]
    assert all("reported_event_date" not in member for member in timeline["members"])


def test_event_timeline_preserves_supported_date_precision_without_reusing_publication_dates(
    tmp_path,
):
    async def event_articles(candidate):
        article = await stored_article(candidate)
        return article.model_copy(
            update={
                "text": {
                    "dense": "The committee met on March 2, 2023. PRIVATE_CHUNK_SENTINEL",
                    "full_text": "The proposal was introduced in January 2022. PRIVATE_CHUNK_SENTINEL",
                    "structural": "Budget coverage has no event date. PRIVATE_CHUNK_SENTINEL",
                }[candidate.chunk_id]
            }
        )

    members = [
        {
            "source_article_id": "https://example.com/structural",
            "reading_direction": "Read the budget discussion; its event date is unavailable.",
            "reported_event_date": "2025-02-02",
        },
        {
            "source_article_id": "https://example.com/full_text",
            "reading_direction": "Read the section on the proposal's introduction.",
            "reported_event_date": "January 2022",
        },
        {
            "source_article_id": "https://example.com/dense",
            "reading_direction": "Read the committee hearing coverage.",
            "reported_event_date": "March 2, 2023",
        },
    ]
    db_path = tmp_path / "guides.db"
    with guide_client(
        db_path=db_path,
        assessment={"status": "allowed", "reading_order": "event_asc"},
        guidance={
            "source_notes": [
                *NOTES,
                {
                    "source_article_id": "https://example.com/structural",
                    "note": "Read the budget discussion.",
                },
            ],
            "groups": [
                {
                    "kind": "timeline",
                    "label": "Read about developments in order",
                    "order": "event_asc",
                    "members": members,
                }
            ],
        },
        load_grounding=event_articles,
    ) as (client, _, _):
        response = submit_guide(
            client, json={"question": "Read about AB 1 events from earliest to latest."}
        )
        guide = response.json()
        assert guide["status"] == "completed"
        timeline = guide["groups"][0]
        assert timeline["order"] == "event_asc"
        assert [member["source_article_id"] for member in timeline["members"]] == [
            "https://example.com/full_text",
            "https://example.com/dense",
            "https://example.com/structural",
        ]
        assert [
            member.get("reported_event_date") for member in timeline["members"]
        ] == ["January 2022", "March 2, 2023", None]
        assert [
            article["citation"]["source_article_id"] for article in guide["articles"]
        ] == [
            "https://example.com/full_text",
            "https://example.com/dense",
            "https://example.com/structural",
        ]
        assert guide["articles"][1]["citation"]["published_date"] == "2025-03-01"
        assert guide["relevance_order"] == [
            "https://example.com/dense",
            "https://example.com/full_text",
            "https://example.com/structural",
        ]
        assert "2025-02-02" not in response.text
        assert "PRIVATE_CHUNK_SENTINEL" not in response.text
    with guide_client(db_path=db_path) as (client, _, _):
        assert client.get(f"/api/guides/{guide['guide_id']}").json() == guide


@pytest.mark.parametrize(
    "groups",
    [
        None,
        [],
        [
            {
                "kind": "aspect",
                "label": "Unavailable aspect",
                "members": [
                    {
                        "source_article_id": "excluded",
                        "reading_direction": "EXCLUDED_DIRECTION",
                    }
                ],
            }
        ],
    ],
)
def test_unavailable_groups_keep_every_passing_article_and_direction(tmp_path, groups):
    guidance = {"source_notes": NOTES}
    if groups is not None:
        guidance["groups"] = groups
    with guide_client(
        db_path=tmp_path / "guides.db", guidance=guidance, load_grounding=stored_article
    ) as (client, _, _):
        response = submit_guide(
            client, json={"question": "Where can I read about AB 1?"}
        )
    guide = response.json()
    assert guide["status"] == "completed"
    assert guide["groups"] == []
    assert [article["reading_direction"] for article in guide["articles"]] == [
        "Read the hearing coverage to investigate the housing debate.",
        "Read the proposal coverage to investigate eligibility.",
    ]
    assert "EXCLUDED_DIRECTION" not in response.text


@pytest.mark.parametrize(
    "failure",
    ["blank", "invalid_kind", "missing_timeline_basis", "provider"],
)
def test_invalid_group_guidance_fails_instead_of_publishing_an_empty_or_ungrouped_success(
    tmp_path, failure
):
    member = {
        "source_article_id": "https://example.com/dense",
        "reading_direction": "Read the hearing's supporters section.",
    }
    group = {"kind": "contrast", "label": "Investigate support", "members": [member]}
    if failure == "blank":
        member["reading_direction"] = " "
    elif failure == "invalid_kind":
        group["kind"] = "party_position"
    elif failure == "missing_timeline_basis":
        group["kind"] = "timeline"
    guidance = (
        RuntimeError("PRIVATE_PROVIDER_FAILURE")
        if failure == "provider"
        else {"source_notes": NOTES, "groups": [group]}
    )
    with guide_client(
        db_path=tmp_path / "guides.db", guidance=guidance, load_grounding=stored_article
    ) as (client, _, _):
        response = submit_guide(
            client,
            json={"question": "Where can I read supporters and detractors of AB 1?"},
        )
    guide = response.json()
    assert guide["status"] == "guidance_failed"
    assert guide["latest_attempt"]["status"] == "failed"
    assert guide["articles"] == []
    assert guide["groups"] == []
    assert "PRIVATE_" not in response.text


def test_optional_publication_view_orders_its_members_without_changing_the_default_relevance_list(
    tmp_path,
):
    with guide_client(
        db_path=tmp_path / "guides.db",
        guidance={
            "source_notes": NOTES,
            "groups": [
                {
                    "kind": "timeline",
                    "label": "Read publication history",
                    "order": "publication_asc",
                    "members": [
                        {
                            "source_article_id": note["source_article_id"],
                            "reading_direction": note["note"],
                        }
                        for note in NOTES
                    ],
                }
            ],
        },
        load_grounding=stored_article,
    ) as (client, _, _):
        guide = submit_guide(
            client, json={"question": "What should I read about AB 1?"}
        ).json()
    assert [
        article["citation"]["source_article_id"] for article in guide["articles"]
    ] == ["https://example.com/dense", "https://example.com/full_text"]
    assert [
        member["source_article_id"] for member in guide["groups"][0]["members"]
    ] == ["https://example.com/full_text", "https://example.com/dense"]


def test_repeated_memberships_keep_distinct_nearby_directions_for_one_included_article(
    tmp_path,
):
    supporters = {
        "source_article_id": "https://example.com/dense",
        "reading_direction": "Read the hearing's supporters section.",
    }
    detractors = {
        "source_article_id": "https://example.com/dense",
        "reading_direction": "Read the hearing's detractors section.",
    }
    db_path = tmp_path / "guides.db"
    with guide_client(
        db_path=db_path,
        guidance={
            "source_notes": NOTES,
            "groups": [
                {
                    "kind": "contrast",
                    "label": "Investigate the housing debate",
                    "members": [supporters, detractors, supporters],
                }
            ],
        },
        load_grounding=stored_article,
    ) as (client, _, _):
        guide = submit_guide(
            client, json={"question": "Where can I read both accounts of AB 1?"}
        ).json()
    assert guide["status"] == "completed"
    assert [
        article["citation"]["source_article_id"] for article in guide["articles"]
    ] == ["https://example.com/dense", "https://example.com/full_text"]
    assert guide["groups"][0]["members"] == [supporters, detractors]
    with guide_client(db_path=db_path) as (client, _, _):
        assert client.get(f"/api/guides/{guide['guide_id']}").json() == guide
