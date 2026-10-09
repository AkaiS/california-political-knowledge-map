"""Application-owned searches observed through HTTP and real SQLite."""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from test_chat_web import completed_guide_async, no_dependencies, stored_article
from test_retrieval import COVERAGE, Branch, coordinator

from knowledge_map.adapters.source_guides import SQLiteGuideStore
from knowledge_map.core.chat import CHAT_INSTRUCTIONS, ChatSession
from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.schemas.retrieval import RetrievalBranch
from knowledge_map.schemas.source_guides import SourceGuide
from knowledge_map.web import create_app


def controlled_app(db_path, respond, *, startup=no_dependencies, branches=None):
    branches = branches or {branch: Branch(branch) for branch in RetrievalBranch}
    agent = Agent(
        FunctionModel(respond),
        output_type=QuestionAssessment,
        instructions=CHAT_INSTRUCTIONS,
        retries=0,
    )

    def session_factory(question, dependencies):
        return ChatSession(
            question,
            chat_agent=agent,
            retrieval=coordinator(
                branches,
                load_grounding=stored_article,
            ),
            coverage=COVERAGE,
            relevant_collection_ids=("reporting",),
        )

    return create_app(
        startup=startup, session_factory=session_factory, guide_db_path=db_path
    )


@asynccontextmanager
async def http_client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        yield client


def test_submission_returns_saved_identity_while_search_waits_for_the_model(tmp_path):
    async def exercise():
        entered, release, finished = (asyncio.Event() for _ in range(3))

        async def respond(messages, info):
            entered.set()
            await release.wait()
            finished.set()
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"status": "needs_edit", "explanation": "Name the bill."},
                    )
                ]
            )

        app = controlled_app(tmp_path / "guides.db", respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            response = await asyncio.wait_for(
                client.post(
                    "/api/questions", json={"question": "Who backed that bill?"}
                ),
                2,
            )
            assert response.status_code == 202
            guide = response.json()
            assert guide["question"] == "Who backed that bill?"
            assert guide["latest_attempt"]["status"] == "running"
            assert "last_retrieved_at" not in guide
            await asyncio.wait_for(entered.wait(), 2)
            assert (await client.get(response.headers["Location"])).json() == guide
            release.set()
            await asyncio.wait_for(finished.wait(), 2)
            completed = (await completed_guide_async(client, response)).json()
            assert completed["status"] == "needs_edit"
            assert (
                completed["latest_attempt"]["attempt_id"]
                == guide["latest_attempt"]["attempt_id"]
            )

    asyncio.run(exercise())


def test_independent_guides_continue_after_clients_disconnect_and_reconnect(tmp_path):
    async def exercise():
        questions = ("Who backed AB 1?", "Who backed SB 2?")
        entered = {question: asyncio.Event() for question in questions}
        release = {question: asyncio.Event() for question in questions}
        calls = []
        branches = {branch: Branch(branch) for branch in RetrievalBranch}

        async def respond(messages, info):
            prompts = [
                part.content
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart)
            ]
            if "question_policy" in json.loads(prompts[-1]):
                question = json.loads(prompts[-1])["question"]
                calls.append(question)
                entered[question].set()
                await release[question].wait()
                output = {"status": "allowed"}
            else:
                output = {
                    "source_notes": [
                        {
                            "source_article_id": "https://example.com/dense",
                            "note": "Read the section on the bill's housing provisions.",
                        }
                    ]
                }
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, output)]
            )

        app = controlled_app(tmp_path / "guides.db", respond, branches=branches)
        async with app.router.lifespan_context(app):
            async with http_client(app) as first_client:
                first = await first_client.post(
                    "/api/questions", json={"question": questions[0]}
                )
                await asyncio.wait_for(entered[questions[0]].wait(), 2)
            async with http_client(app) as second_client:
                second = await second_client.post(
                    "/api/questions", json={"question": questions[1]}
                )
                await asyncio.wait_for(entered[questions[1]].wait(), 2)
                for response in (first, second, first):
                    assert (
                        await second_client.get(response.headers["Location"])
                    ).json()["status"] == "running"
            release[questions[1]].set()
            async with http_client(app) as reconnected:
                completed = (await completed_guide_async(reconnected, second)).json()
                assert completed["question"] == questions[1]
                assert completed["status"] == "completed"
                assert (
                    completed["articles"][0]["citation"]["url"]
                    == "https://example.com/dense"
                )
                assert (
                    completed["last_retrieved_at"]
                    == completed["latest_attempt"]["finished_at"]
                )
                listing = (await reconnected.get("/api/guides")).json()["guides"]
                assert {
                    guide["question"]: guide["latest_attempt"]["status"]
                    for guide in listing
                } == {
                    questions[0]: "running",
                    questions[1]: "completed",
                }
                release[questions[0]].set()
                completed_first = (
                    await completed_guide_async(reconnected, first)
                ).json()
                assert completed_first["question"] == questions[0]
                assert completed_first["guide_id"] != completed["guide_id"]
                assert (
                    await reconnected.get(second.headers["Location"])
                ).json() == completed
                assert calls == list(questions)
                for branch in branches.values():
                    assert [
                        request.rewrite.question for request, _ in branch.requests
                    ] == list(reversed(questions))

    asyncio.run(exercise())


def test_obsolete_or_wrong_guide_completion_cannot_publish_content_or_timestamps(
    tmp_path,
):
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        async def respond(messages, info):
            entered.set()
            await release.wait()
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"status": "needs_edit", "explanation": "Name the bill."},
                    )
                ]
            )

        db_path = tmp_path / "guides.db"
        app = controlled_app(db_path, respond)
        store = SQLiteGuideStore(db_path)
        async with app.router.lifespan_context(app), http_client(app) as client:
            response = await client.post(
                "/api/questions", json={"question": "Who backed AB 1?"}
            )
            await asyncio.wait_for(entered.wait(), 2)
            first = response.json()
            other = store.create("Who backed SB 2?")
            result = SourceGuide(question=first["question"], status="empty")
            for obsolete in (other.latest_attempt.attempt_id, "older-attempt"):
                store.finish(first["guide_id"], obsolete, result)
                assert (await client.get(response.headers["Location"])).json() == first
            store.finish(
                first["guide_id"], first["latest_attempt"]["attempt_id"], result
            )
            published = (await client.get(response.headers["Location"])).json()
            assert published["status"] == "empty"
            assert (
                published["last_retrieved_at"]
                == published["latest_attempt"]["finished_at"]
            )
            store.finish(
                first["guide_id"],
                first["latest_attempt"]["attempt_id"],
                SourceGuide(question=first["question"], status="assessment_failed"),
            )
            assert (await client.get(response.headers["Location"])).json() == published
            release.set()
        async with http_client(app) as client:
            assert (await client.get(response.headers["Location"])).json() == published
            assert (await client.get(f"/api/guides/{other.guide_id}")).json()[
                "status"
            ] == "running"

    asyncio.run(exercise())


def test_application_shutdown_stops_work_before_closing_shared_dependencies(tmp_path):
    async def exercise():
        entered = asyncio.Event()
        lifecycle = []

        @asynccontextmanager
        async def startup():
            lifecycle.append("dependencies opened")
            yield None
            lifecycle.append("dependencies closed")

        async def respond(messages, info):
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                lifecycle.append("model stopped")

        app = controlled_app(tmp_path / "guides.db", respond, startup=startup)
        async with app.router.lifespan_context(app):
            async with http_client(app) as client:
                response = await client.post(
                    "/api/questions", json={"question": "Who backed AB 1?"}
                )
                await asyncio.wait_for(entered.wait(), 2)
            assert lifecycle == ["dependencies opened"]
        assert lifecycle == [
            "dependencies opened",
            "model stopped",
            "dependencies closed",
        ]
        async with http_client(app) as client:
            guide = (await client.get(response.headers["Location"])).json()
            assert guide["latest_attempt"]["status"] == "interrupted"
            assert "last_retrieved_at" not in guide
            assert (
                await client.post(
                    "/api/questions", json={"question": "Another question?"}
                )
            ).status_code == 503

    asyncio.run(exercise())


def test_disconnection_during_submission_response_does_not_cancel_saved_work(tmp_path):
    async def exercise():
        entered, release, sending = (asyncio.Event() for _ in range(3))
        calls = []

        async def respond(messages, info):
            calls.append("assessment")
            entered.set()
            await release.wait()
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"status": "needs_edit", "explanation": "Name the bill."},
                    )
                ]
            )

        app = controlled_app(tmp_path / "guides.db", respond)

        async def disconnected_response(scope, receive, send):
            async def hold_response(message):
                sending.set()
                await asyncio.Event().wait()

            await app(scope, receive, hold_response)

        async with app.router.lifespan_context(app), http_client(app) as reconnected:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=disconnected_response),
                base_url="http://localhost",
            ) as browser:
                request = asyncio.create_task(
                    browser.post(
                        "/api/questions", json={"question": "Who backed that bill?"}
                    )
                )
                await asyncio.wait_for(sending.wait(), 2)
                await asyncio.wait_for(entered.wait(), 2)
                request.cancel()
                try:
                    await request
                except asyncio.CancelledError:
                    pass
            saved = (await reconnected.get("/api/guides")).json()["guides"]
            assert len(saved) == 1
            assert saved[0]["latest_attempt"]["status"] == "running"
            release.set()
            # The disconnected browser never received the saved identity.
            current = await reconnected.get(f"/api/guides/{saved[0]['guide_id']}")
            result = (await completed_guide_async(reconnected, current)).json()
            assert result["status"] == "needs_edit"
            assert calls == ["assessment"]

    asyncio.run(exercise())
