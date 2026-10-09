"""Attempt cancellation observed through HTTP and durable reader content."""

import asyncio

import pytest
from test_chat_web import completed_guide_async
from test_source_guide_execution import controlled_app, http_client
from test_source_guide_updates import article_guidance, model_output, question_input

from knowledge_map.adapters.source_guides import SQLiteGuideStore
from knowledge_map.schemas.source_guides import SourceGuide


def cancel_url(response):
    guide = response.json()
    return (
        f"/api/guides/{guide['guide_id']}/attempts/"
        f"{guide['latest_attempt']['attempt_id']}/cancel"
    )


def test_cancel_initial_search_persists_question_outcome_and_timing_without_replay(
    tmp_path,
):
    async def exercise():
        entered, stopped = asyncio.Event(), asyncio.Event()
        questions = []

        async def respond(messages, info):
            questions.append(question_input(messages)["question"])
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                stopped.set()
            return model_output(info, {"status": "allowed"})

        db_path = tmp_path / "guides.db"
        app = controlled_app(db_path, respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            submitted = await client.post(
                "/api/questions", json={"question": "Who backed AB 1 in 2025?"}
            )
            await asyncio.wait_for(entered.wait(), 2)
            response = await client.post(cancel_url(submitted), json={})
            assert response.status_code == 200
            cancelled = response.json()
            assert cancelled["question"] == "Who backed AB 1 in 2025?"
            assert cancelled["guide_id"] == submitted.json()["guide_id"]
            assert cancelled["created_at"] == submitted.json()["created_at"]
            assert cancelled["status"] == "cancelled"
            assert cancelled["articles"] == []
            assert "last_retrieved_at" not in cancelled
            attempt = cancelled["latest_attempt"]
            assert (
                attempt["attempt_id"]
                == submitted.json()["latest_attempt"]["attempt_id"]
            )
            assert (
                attempt["started_at"]
                == submitted.json()["latest_attempt"]["started_at"]
            )
            assert attempt["status"] == attempt["outcome"] == "cancelled"
            assert attempt["finished_at"] >= attempt["started_at"]
            await asyncio.wait_for(stopped.wait(), 2)
            assert (await client.get(submitted.headers["Location"])).json() == cancelled
            assert (
                await client.post(cancel_url(submitted), json={})
            ).json() == cancelled
            SQLiteGuideStore(db_path).finish(
                cancelled["guide_id"],
                attempt["attempt_id"],
                SourceGuide(question=cancelled["question"], status="empty"),
            )
            assert (await client.get(submitted.headers["Location"])).json() == cancelled
        reopened = controlled_app(db_path, respond)
        async with (
            reopened.router.lifespan_context(reopened),
            http_client(reopened) as client,
        ):
            assert (await client.get(submitted.headers["Location"])).json() == cancelled
            listing = (await client.get("/api/guides")).json()["guides"]
            assert listing[0]["latest_attempt"] == {
                field: cancelled["latest_attempt"][field]
                for field in (
                    "attempt_id",
                    "started_at",
                    "finished_at",
                    "status",
                    "outcome",
                )
            }
            assert questions == ["Who backed AB 1 in 2025?"]

    asyncio.run(exercise())


def test_cancel_preserves_json_and_loopback_admission_boundaries(tmp_path):
    async def exercise():
        entered = asyncio.Event()

        async def respond(messages, info):
            entered.set()
            await asyncio.Event().wait()
            return model_output(info, {"status": "allowed"})

        app = controlled_app(tmp_path / "guides.db", respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            submitted = await client.post(
                "/api/questions", json={"question": "Who backed AB 1?"}
            )
            await asyncio.wait_for(entered.wait(), 2)
            url = cancel_url(submitted)
            assert (
                await client.post(
                    url, content="{}", headers={"Content-Type": "text/plain"}
                )
            ).status_code == 415
            for body in (
                {"attempt_id": "other"},
                {"question": "Who backed SB 2?"},
                {"model": "other"},
            ):
                assert (await client.post(url, json=body)).status_code == 422
            assert (
                await client.post(url, json={}, headers={"Host": "attacker.example"})
            ).status_code == 421
            assert (
                await client.post(
                    "/api/guides/missing/attempts/missing/cancel", json={}
                )
            ).status_code == 404
            assert (
                await client.get(submitted.headers["Location"])
            ).json() == submitted.json()
        async with http_client(app) as client:
            assert (await client.post(url, json={})).status_code == 503

    asyncio.run(exercise())


def test_cancel_is_bound_to_one_attempt_while_another_guide_continues(tmp_path):
    async def exercise():
        questions = ("Who backed AB 1?", "Who backed SB 2?")
        entered = {question: asyncio.Event() for question in questions}
        release = {question: asyncio.Event() for question in questions}
        stopped = {question: asyncio.Event() for question in questions}

        async def respond(messages, info):
            prompt = question_input(messages)
            if "question_policy" in prompt:
                question = prompt["question"]
                try:
                    entered[question].set()
                    await release[question].wait()
                finally:
                    stopped[question].set()
                return model_output(info, {"status": "allowed"})
            return model_output(info, article_guidance("Read the housing provisions."))

        app = controlled_app(tmp_path / "guides.db", respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            first, second = [
                await client.post("/api/questions", json={"question": question})
                for question in questions
            ]
            for event in entered.values():
                await asyncio.wait_for(event.wait(), 2)
            wrong_guide_url = cancel_url(second).replace(
                second.json()["guide_id"], first.json()["guide_id"]
            )
            assert (await client.post(wrong_guide_url, json={})).json() == first.json()
            cancelled = (await client.post(cancel_url(first), json={})).json()
            await asyncio.wait_for(stopped[questions[0]].wait(), 2)
            assert cancelled["latest_attempt"]["status"] == "cancelled"
            assert (
                await client.get(second.headers["Location"])
            ).json() == second.json()
            release[questions[1]].set()
            completed = (await completed_guide_async(client, second)).json()
            assert completed["latest_attempt"]["status"] == "completed"
            assert len(completed["articles"]) == 1
            assert (await client.get(first.headers["Location"])).json() == cancelled
            assert {
                guide["question"]: guide["latest_attempt"]["status"]
                for guide in (await client.get("/api/guides")).json()["guides"]
            } == {
                questions[0]: "cancelled",
                questions[1]: "completed",
            }

    asyncio.run(exercise())


@pytest.mark.parametrize("order", ["cancel_first", "completion_first", "concurrent"])
def test_cancel_and_completion_publish_one_consistent_terminal_result(tmp_path, order):
    async def exercise():
        entered = asyncio.Event()
        questions = []

        async def respond(messages, info):
            prompt = question_input(messages)
            if "question_policy" in prompt:
                questions.append(prompt["question"])
                if len(questions) == 2:
                    entered.set()
                    await asyncio.Event().wait()
                return model_output(info, {"status": "allowed"})
            return model_output(
                info, article_guidance("Read the original housing provisions.")
            )

        db_path = tmp_path / "guides.db"
        app = controlled_app(db_path, respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            initial = await client.post(
                "/api/questions", json={"question": "Who backed AB 1?"}
            )
            saved = (await completed_guide_async(client, initial)).json()
            update = await client.post(f"{initial.headers['Location']}/update", json={})
            await asyncio.wait_for(entered.wait(), 2)
            store = SQLiteGuideStore(db_path)
            result = SourceGuide.model_validate(
                {
                    "question": saved["question"],
                    "status": "completed",
                    "partial": True,
                    "articles": [
                        {
                            "citation": saved["articles"][0]["citation"],
                            "reading_direction": "Read the revised housing provisions.",
                        }
                    ],
                }
            )

            async def complete():
                await asyncio.to_thread(
                    store.finish,
                    saved["guide_id"],
                    update.json()["latest_attempt"]["attempt_id"],
                    result,
                )

            if order == "cancel_first":
                response = await client.post(cancel_url(update), json={})
                await complete()
            elif order == "completion_first":
                await complete()
                response = await client.post(cancel_url(update), json={})
            else:
                _, response = await asyncio.gather(
                    complete(), client.post(cancel_url(update), json={})
                )
            assert response.status_code == 200
            terminal = (await client.get(initial.headers["Location"])).json()
            assert response.json() == terminal
            attempt = terminal["latest_attempt"]
            assert attempt["status"] in {"completed", "cancelled"}
            if order != "concurrent":
                assert attempt["status"] == (
                    "cancelled" if order == "cancel_first" else "completed"
                )
            assert attempt["outcome"] == attempt["status"]
            assert attempt["finished_at"] >= attempt["started_at"]
            if attempt["status"] == "cancelled":
                for field in ("articles", "partial", "last_retrieved_at"):
                    assert terminal[field] == saved[field]
            else:
                assert (
                    terminal["articles"]
                    == result.model_dump(mode="json", exclude_none=True)["articles"]
                )
                assert terminal["partial"] is True
                assert terminal["last_retrieved_at"] == attempt["finished_at"]
                assert terminal["last_retrieved_at"] > saved["last_retrieved_at"]
            await complete()
            assert (await client.post(cancel_url(update), json={})).json() == terminal
            assert (await client.get(initial.headers["Location"])).json() == terminal
        reopened = controlled_app(db_path, respond)
        async with (
            reopened.router.lifespan_context(reopened),
            http_client(reopened) as client,
        ):
            assert (await client.get(initial.headers["Location"])).json() == terminal
            assert questions == ["Who backed AB 1?"] * 2

    asyncio.run(exercise())


def test_cancel_update_retains_reading_rejects_late_results_and_allows_explicit_update(
    tmp_path,
):
    async def exercise():
        entered, stopped, updating, release = (asyncio.Event() for _ in range(4))
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
                if len(questions) == 2:
                    try:
                        entered.set()
                        await asyncio.Event().wait()
                    finally:
                        stopped.set()
                if len(questions) == 3:
                    updating.set()
                    await release.wait()
                return model_output(info, {"status": "allowed"})
            return model_output(
                info,
                article_guidance(
                    "Read the original housing provisions."
                    if len(questions) == 1
                    else "Read the updated housing provisions."
                ),
            )

        db_path = tmp_path / "guides.db"
        app = controlled_app(db_path, respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            initial = await client.post(
                "/api/questions", json={"question": "Who backed AB 1?"}
            )
            saved = (await completed_guide_async(client, initial)).json()
            update = await client.post(f"{initial.headers['Location']}/update", json={})
            await asyncio.wait_for(entered.wait(), 2)
            cancelled_response = await client.post(cancel_url(update), json={})
            assert cancelled_response.status_code == 200
            cancelled = cancelled_response.json()
            for field in (
                "question",
                "guide_id",
                "created_at",
                "status",
                "articles",
                "assessment",
                "message",
                "last_retrieved_at",
            ):
                assert cancelled[field] == saved[field]
            assert cancelled["latest_attempt"]["status"] == "cancelled"
            assert cancelled["latest_attempt"]["outcome"] == "cancelled"
            assert (
                cancelled["latest_attempt"]["started_at"] > saved["last_retrieved_at"]
            )
            assert (
                cancelled["latest_attempt"]["finished_at"]
                >= cancelled["latest_attempt"]["started_at"]
            )
            await asyncio.wait_for(stopped.wait(), 2)
            store = SQLiteGuideStore(db_path)
            late_result = SourceGuide(question=saved["question"], status="empty")
            store.finish(
                saved["guide_id"],
                update.json()["latest_attempt"]["attempt_id"],
                late_result,
            )
            assert (await client.get(initial.headers["Location"])).json() == cancelled
        reopened = controlled_app(db_path, respond)
        async with (
            reopened.router.lifespan_context(reopened),
            http_client(reopened) as client,
        ):
            assert (await client.get(initial.headers["Location"])).json() == cancelled
            assert questions == ["Who backed AB 1?"] * 2
            next_update = await client.post(
                f"{initial.headers['Location']}/update", json={}
            )
            assert next_update.status_code == 202
            await asyncio.wait_for(updating.wait(), 2)
            running = (await client.get(initial.headers["Location"])).json()
            assert running["latest_attempt"]["status"] == "running"
            assert (
                running["latest_attempt"]["attempt_id"]
                != cancelled["latest_attempt"]["attempt_id"]
            )
            assert (await client.post(cancel_url(update), json={})).json() == running
            store.finish(
                saved["guide_id"],
                update.json()["latest_attempt"]["attempt_id"],
                late_result,
            )
            assert (await client.get(initial.headers["Location"])).json() == running
            release.set()
            updated = (await completed_guide_async(client, next_update)).json()
            assert updated["latest_attempt"]["status"] == "completed"
            assert (
                updated["articles"][0]["reading_direction"]
                == "Read the updated housing provisions."
            )
            assert updated["last_retrieved_at"] > saved["last_retrieved_at"]
            assert questions == ["Who backed AB 1?"] * 3

    asyncio.run(exercise())
