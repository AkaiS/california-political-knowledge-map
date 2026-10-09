"""Explicit guide updates and edited questions through HTTP and real SQLite."""

import asyncio
import json

from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from test_chat_web import completed_guide_async
from test_source_guide_execution import controlled_app, http_client

from knowledge_map.adapters.source_guides import SQLiteGuideStore
from knowledge_map.schemas.source_guides import SourceGuide


def question_input(messages):
    return json.loads(
        [
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        ][-1]
    )


def model_output(info, output):
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])


def article_guidance(note):
    return {
        "source_notes": [
            {"source_article_id": "https://example.com/dense", "note": note}
        ]
    }


def test_update_keeps_identity_and_reading_until_new_content_is_published(tmp_path):
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        questions = []

        async def respond(messages, info):
            prompt = question_input(messages)
            if "question_policy" in prompt:
                questions.append(prompt["question"])
                if len(questions) == 2:
                    entered.set()
                    await release.wait()
                return model_output(info, {"status": "allowed"})
            return model_output(
                info,
                article_guidance(
                    "Read the housing provisions."
                    if len(questions) == 1
                    else "Read the updated discussion of housing provisions."
                ),
            )

        app = controlled_app(tmp_path / "guides.db", respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            first = await client.post(
                "/api/questions", json={"question": "Who backed AB 1?"}
            )
            saved = (await completed_guide_async(client, first)).json()
            assert saved["status"] == "completed"
            update = await client.post(f"{first.headers['Location']}/update", json={})
            assert update.status_code == 202
            await asyncio.wait_for(entered.wait(), 2)
            running = (await client.get(first.headers["Location"])).json()
            assert running["guide_id"] == saved["guide_id"]
            assert running["question"] == saved["question"]
            assert running["created_at"] == saved["created_at"]
            assert running["articles"] == saved["articles"]
            assert running["last_retrieved_at"] == saved["last_retrieved_at"]
            assert running["latest_attempt"]["status"] == "running"
            assert (
                running["latest_attempt"]["attempt_id"]
                != saved["latest_attempt"]["attempt_id"]
            )
            assert "finished_at" not in running["latest_attempt"]
            release.set()
            updated = (await completed_guide_async(client, update)).json()
            assert updated["guide_id"] == saved["guide_id"]
            assert updated["latest_attempt"]["status"] == "completed"
            assert updated["articles"][0]["reading_direction"] == (
                "Read the updated discussion of housing provisions."
            )
            assert updated["last_retrieved_at"] > saved["last_retrieved_at"]
            assert (
                updated["last_retrieved_at"] == updated["latest_attempt"]["finished_at"]
            )
            assert len((await client.get("/api/guides")).json()["guides"]) == 1
            assert questions == ["Who backed AB 1?", "Who backed AB 1?"]

    asyncio.run(exercise())


def test_failed_update_preserves_saved_reading_and_its_retrieval_date(tmp_path):
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        questions = []

        async def respond(messages, info):
            prompt = question_input(messages)
            if "question_policy" in prompt:
                questions.append(prompt["question"])
                if len(questions) == 1:
                    return model_output(
                        info,
                        {
                            "status": "deferred",
                            "explanation": "Complete roll calls are unavailable.",
                            "recoverable_portion": "Reporting can identify some votes.",
                        },
                    )
                entered.set()
                await release.wait()
                return model_output(info, {"status": "allowed"})
            if len(questions) == 2:
                raise RuntimeError("PRIVATE_PROVIDER_FAILURE")
            return model_output(info, article_guidance("Read the housing provisions."))

        db_path = tmp_path / "guides.db"
        app = controlled_app(db_path, respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            first = await client.post(
                "/api/questions", json={"question": "Who backed AB 1?"}
            )
            saved = (await completed_guide_async(client, first)).json()
            update = await client.post(f"{first.headers['Location']}/update", json={})
            await asyncio.wait_for(entered.wait(), 2)
            release.set()
            failed = (await completed_guide_async(client, update)).json()
            for field in ("articles", "assessment", "message", "last_retrieved_at"):
                assert failed[field] == saved[field]
            assert failed["latest_attempt"]["status"] == "failed"
            assert failed["latest_attempt"]["outcome"] == "guidance_failed"
            assert failed["latest_attempt"]["assessment"]["status"] == "allowed"
            assert failed["latest_attempt"]["message"].startswith(
                "Reading directions could not be prepared."
            )
            assert failed["latest_attempt"]["started_at"] > saved["last_retrieved_at"]
            assert failed["latest_attempt"]["finished_at"] > saved["last_retrieved_at"]
            assert "PRIVATE_" not in json.dumps(failed)
        reopened = controlled_app(db_path, respond)
        async with (
            reopened.router.lifespan_context(reopened),
            http_client(reopened) as client,
        ):
            assert (await client.get(first.headers["Location"])).json() == failed
            listing = (await client.get("/api/guides")).json()["guides"]
            assert listing[0]["latest_attempt"]["status"] == "failed"
            assert listing[0]["last_retrieved_at"] == saved["last_retrieved_at"]
            assert questions == ["Who backed AB 1?", "Who backed AB 1?"]

    asyncio.run(exercise())


def test_update_rejects_simple_cross_origin_posts_and_question_or_model_overrides(
    tmp_path,
):
    async def exercise():
        questions = []

        async def respond(messages, info):
            prompt = question_input(messages)
            if "question_policy" in prompt:
                questions.append(prompt["question"])
                return model_output(info, {"status": "allowed"})
            return model_output(info, {"source_notes": []})

        app = controlled_app(tmp_path / "guides.db", respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            first = await client.post(
                "/api/questions", json={"question": "Who backed AB 1?"}
            )
            saved = (await completed_guide_async(client, first)).json()
            url = f"{first.headers['Location']}/update"
            response = await client.post(
                url, content="{}", headers={"Content-Type": "text/plain"}
            )
            assert response.status_code == 415
            for body in ({"question": "Who backed SB 2?"}, {"model": "other"}):
                assert (await client.post(url, json=body)).status_code == 422
            assert (await client.get(first.headers["Location"])).json() == saved
            assert questions == ["Who backed AB 1?"]
            assert (
                await client.post(url, json={}, headers={"Host": "attacker.example"})
            ).status_code == 421
            assert (
                await client.post("/api/guides/missing/update", json={})
            ).status_code == 404
        async with http_client(app) as client:
            assert (await client.post(url, json={})).status_code == 503

    asyncio.run(exercise())


def test_conflicting_updates_wait_for_completion_and_empty_update_replaces_reading(
    tmp_path,
):
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        questions = []

        async def respond(messages, info):
            prompt = question_input(messages)
            if "question_policy" in prompt:
                questions.append(prompt["question"])
                if len(questions) == 2:
                    entered.set()
                    await release.wait()
                return model_output(info, {"status": "allowed"})
            return model_output(
                info,
                {"source_notes": []}
                if len(questions) == 3
                else article_guidance("Read the housing provisions."),
            )

        db_path = tmp_path / "guides.db"
        app = controlled_app(db_path, respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            first = await client.post(
                "/api/questions", json={"question": "Who backed AB 1?"}
            )
            saved = (await completed_guide_async(client, first)).json()
            url = f"{first.headers['Location']}/update"
            responses = await asyncio.gather(
                client.post(url, json={}), client.post(url, json={})
            )
            assert sorted(response.status_code for response in responses) == [202, 409]
            accepted = next(
                response for response in responses if response.status_code == 202
            )
            await asyncio.wait_for(entered.wait(), 2)
            running = (await client.get(first.headers["Location"])).json()
            assert running["articles"] == saved["articles"]
            assert running["latest_attempt"] == accepted.json()["latest_attempt"]
            store = SQLiteGuideStore(db_path)
            store.finish(
                saved["guide_id"],
                saved["latest_attempt"]["attempt_id"],
                SourceGuide(question=saved["question"], status="empty"),
            )
            assert (await client.get(first.headers["Location"])).json() == running
            release.set()
            updated = (await completed_guide_async(client, accepted)).json()
            empty_response = await client.post(url, json={})
            assert empty_response.status_code == 202
            empty = (await completed_guide_async(client, empty_response)).json()
            assert empty["guide_id"] == saved["guide_id"]
            assert empty["status"] == "empty"
            assert empty["articles"] == []
            assert empty["latest_attempt"]["status"] == "empty"
            assert empty["last_retrieved_at"] > updated["last_retrieved_at"]
            assert empty["last_retrieved_at"] == empty["latest_attempt"]["finished_at"]
            assert (
                len(
                    {
                        guide["latest_attempt"]["attempt_id"]
                        for guide in (saved, updated, empty)
                    }
                )
                == 3
            )
            store.finish(
                saved["guide_id"],
                updated["latest_attempt"]["attempt_id"],
                SourceGuide(question=saved["question"], status="assessment_failed"),
            )
            assert (await client.get(first.headers["Location"])).json() == empty
            assert questions == ["Who backed AB 1?"] * 3

    asyncio.run(exercise())


def test_edited_complete_question_creates_an_independent_guide_without_rewriting(
    tmp_path,
):
    async def exercise():
        questions = []

        async def respond(messages, info):
            prompt = question_input(messages)
            if "question_policy" in prompt:
                questions.append(prompt["question"])
                return model_output(info, {"status": "allowed"})
            return model_output(info, article_guidance("Read the housing provisions."))

        app = controlled_app(tmp_path / "guides.db", respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            original_question = "Who backed AB 1's housing provisions in 2025?"
            edited_question = "Who opposed AB 1's housing provisions in 2025, and why?"
            first = await client.post(
                "/api/questions", json={"question": original_question}
            )
            saved = (await completed_guide_async(client, first)).json()
            edited = await client.post(
                "/api/questions", json={"question": edited_question}
            )
            other = (await completed_guide_async(client, edited)).json()
            assert other["guide_id"] != saved["guide_id"]
            assert (
                other["latest_attempt"]["attempt_id"]
                != saved["latest_attempt"]["attempt_id"]
            )
            assert other["question"] == edited_question
            for _ in range(3):
                assert (await client.get(first.headers["Location"])).json() == saved
                assert (await client.get(edited.headers["Location"])).json() == other
                assert len((await client.get("/api/guides")).json()["guides"]) == 2
            assert questions == [original_question, edited_question]

    asyncio.run(exercise())
