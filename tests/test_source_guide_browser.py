"""Opt-in reader checks: RUN_SOURCE_GUIDE_BROWSER_TESTS=1 uv run --with playwright pytest this-file."""

import json
import os

import pytest
from anyio import sleep_forever
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from starlette.testclient import TestClient
from test_chat_web import guide_client, submit_guide
from test_retrieval import Branch, candidate
from test_source_guide_execution import controlled_app

from knowledge_map.schemas.retrieval import (
    GroundingEvidence,
    RetrievalBranch,
    SourceArticleCitation,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SOURCE_GUIDE_BROWSER_TESTS") != "1",
    reason="Opt in after installing Chromium with uv run playwright install chromium",
)
RUNNING_QUESTION = "What should I read about California housing while this search runs?"


@pytest.fixture(params=[{"width": 1120, "height": 1000}, {"width": 390, "height": 844}])
def reader(tmp_path, request):
    playwright = pytest.importorskip("playwright.sync_api")

    async def respond(messages, info):
        prompts = [
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        ]
        data = json.loads(prompts[-1])
        if data.get("question") == RUNNING_QUESTION:
            await sleep_forever()
        output = (
            {"status": "allowed"} if "question_policy" in data else {"source_notes": []}
        )
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

    app = controlled_app(tmp_path / "guides.db", respond)
    with TestClient(app, base_url="http://localhost") as client:
        for number in range(14):
            submit_guide(
                client,
                json={
                    "question": f"What should I read about California housing proposal {number}?"
                },
            )
        with playwright.sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            page = browser.new_page(viewport=request.param)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def application(route):
                response = client.request(
                    route.request.method,
                    route.request.url,
                    headers=route.request.headers,
                    content=route.request.post_data,
                )
                route.fulfill(
                    status=response.status_code,
                    headers=dict(response.headers),
                    body=response.content,
                )

            page.route("http://localhost/**", application)
            page.goto("http://localhost/")
            playwright.expect(
                page.get_by_role("navigation", name="Saved guides").get_by_role("link")
            ).to_have_count(14)
            yield page, playwright.expect
            assert errors == []
            browser.close()


def test_open_saved_guide_reaches_the_selected_question(reader):
    page, expect = reader
    link = page.get_by_role("navigation", name="Saved guides").get_by_role("link").first
    question = link.inner_text()
    link.click()
    expect(page.get_by_role("heading", name=question, exact=True)).to_be_in_viewport(
        ratio=1
    )
    link.click()
    expect(page.get_by_role("heading", name=question, exact=True)).to_be_in_viewport(
        ratio=1
    )


def test_restored_guide_stays_visible_when_saved_list_arrives_later(reader):
    page, expect = reader
    link = page.get_by_role("navigation", name="Saved guides").get_by_role("link").first
    question = link.inner_text()
    url = f"http://localhost/{link.get_attribute('href')}"
    pending = []
    page.route("http://localhost/api/guides", lambda route: pending.append(route))
    page.goto("about:blank")
    with page.expect_response("http://localhost/api/guides/*"):
        page.goto(url)
    heading = page.get_by_role("heading", name=question, exact=True)
    pending.pop().fallback()
    expect(
        page.get_by_role("navigation", name="Saved guides").get_by_role("link")
    ).to_have_count(14)
    expect(heading).to_be_in_viewport(ratio=1)


def test_new_and_edit_question_keep_the_input_visible_and_focused(reader):
    page, expect = reader
    link = page.get_by_role("navigation", name="Saved guides").get_by_role("link").first
    question = link.inner_text()
    link.click()
    page.get_by_role("button", name="Edit question", exact=True).click()
    input = page.get_by_role("textbox", name="Complete question")
    expect(input).to_have_value(question)
    expect(input).to_be_focused()
    expect(input).to_be_in_viewport(ratio=1)
    page.get_by_role("button", name="New question", exact=True).click()
    expect(input).to_have_value("")
    expect(input).to_be_focused()
    expect(input).to_be_in_viewport(ratio=1)


def test_delayed_open_cannot_pull_the_reader_away_from_new_question(reader):
    page, expect = reader
    pending = []
    page.route("http://localhost/api/guides/*", lambda route: pending.append(route))
    page.get_by_role("navigation", name="Saved guides").get_by_role(
        "link"
    ).first.click()
    expect(page.get_by_role("status").first).to_have_text("Opening saved guide…")
    page.get_by_role("button", name="New question", exact=True).click()
    with page.expect_response("http://localhost/api/guides/*"):
        pending.pop().fallback()
    input = page.get_by_role("textbox", name="Complete question")
    expect(input).to_have_value("")
    expect(input).to_be_focused()
    expect(input).to_be_in_viewport(ratio=1)
    expect(page.get_by_role("region")).not_to_be_visible()


def test_running_guide_poll_preserves_the_readers_scroll_position(reader):
    page, expect = reader
    input = page.get_by_role("textbox", name="Complete question")
    input.fill(RUNNING_QUESTION)
    page.get_by_role("button", name="Find articles", exact=True).click()
    expect(
        page.get_by_role("heading", name=RUNNING_QUESTION, exact=True)
    ).to_be_visible()
    page.get_by_role("button", name="New question", exact=True).click()
    page.get_by_role("navigation", name="Saved guides").get_by_role(
        "link", name=RUNNING_QUESTION, exact=True
    ).click()
    expect(
        page.get_by_role("heading", name=RUNNING_QUESTION, exact=True)
    ).to_be_in_viewport(ratio=1)
    page.mouse.wheel(0, -10000)
    expect(input).to_be_in_viewport(ratio=1)
    for _ in range(2):
        with page.expect_response("http://localhost/api/guides/*"):
            pass
        page.evaluate("new Promise(requestAnimationFrame)")
        expect(input).to_be_in_viewport(ratio=1)


@pytest.mark.parametrize(
    "viewport", [{"width": 1120, "height": 1000}, {"width": 390, "height": 844}]
)
@pytest.mark.parametrize(
    "requested", ["publication_asc", "publication_desc", "relevance"]
)
def test_publication_views_use_stated_days_and_keep_all_saved_articles(
    tmp_path, viewport, requested
):
    playwright = pytest.importorskip("playwright.sync_api")
    dates = {
        "later-day": "2024-01-02T00:30:00+02:00",
        "invalid": "2024-02-30",
        "earlier-day": "2024-01-01T23:00:00Z",
        "equal-day": "2024-01-02T20:00:00Z",
        "missing": None,
        "incomplete": "2024-01",
        "ungrouped": "2023-12-31",
    }
    identities = {name: f"https://example.com/{name}" for name in dates}
    branches = {
        branch: Branch(
            branch,
            tuple(
                candidate(branch, name, rank).model_copy(
                    update={"source_article_id": identities[name]}
                )
                for rank, name in enumerate(dates, 1)
            ),
        )
        for branch in RetrievalBranch
    }

    async def grounding(item):
        return GroundingEvidence(
            chunk_id=item.chunk_id,
            text="The committee discussed housing grants.",
            citation=SourceArticleCitation(
                source_article_id=item.source_article_id,
                title=item.chunk_id,
                url=item.source_article_id,
                published_date=dates[item.chunk_id],
            ),
        )

    groups = [
        {
            "kind": "timeline",
            "label": order,
            "order": order,
            "members": [
                {
                    "source_article_id": identity,
                    "reading_direction": "Read the grant discussion.",
                }
                for name, identity in identities.items()
                if name != "ungrouped"
            ],
        }
        for order in ("publication_asc", "publication_desc")
    ]
    orders = {
        "publication_asc": [
            "ungrouped",
            "earlier-day",
            "later-day",
            "equal-day",
            "invalid",
            "missing",
            "incomplete",
        ],
        "publication_desc": [
            "later-day",
            "equal-day",
            "earlier-day",
            "ungrouped",
            "invalid",
            "missing",
            "incomplete",
        ],
        "relevance": list(dates),
    }
    with guide_client(
        db_path=tmp_path / "guides.db",
        branches=branches,
        load_grounding=grounding,
        assessment={"status": "allowed", "reading_order": requested},
        guidance={
            "source_notes": [
                {"source_article_id": identity, "note": "Read the grant discussion."}
                for identity in identities.values()
            ],
            "groups": groups,
        },
    ) as (client, _, _):
        guide = submit_guide(
            client, json={"question": "Where should I read about housing grants?"}
        ).json()
        assert guide["status"] == "completed"
        with playwright.sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            page = browser.new_page(viewport=viewport)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def application(route):
                response = client.request(
                    route.request.method,
                    route.request.url,
                    headers=route.request.headers,
                    content=route.request.post_data,
                )
                route.fulfill(
                    status=response.status_code,
                    headers=dict(response.headers),
                    body=response.content,
                )

            page.route("http://localhost/**", application)
            page.goto(f"http://localhost/#guide={guide['guide_id']}")
            links = page.locator("#articles > li > a")
            playwright.expect(links).to_have_text(orders[requested])
            select = page.get_by_label("Reading view")
            for index, group_order in enumerate(
                ("publication_asc", "publication_desc")
            ):
                select.select_option(f"group:{index}")
                effective = requested if requested != "relevance" else group_order
                playwright.expect(links).to_have_text(orders[effective])
            select.select_option("relevance")
            playwright.expect(links).to_have_text(orders["relevance"])
            page.reload()
            playwright.expect(links).to_have_text(orders[requested])
            assert errors == []
            browser.close()
