"""Explicit recovery after service restart, observed through HTTP and real SQLite."""

import asyncio

from test_chat_web import completed_guide_async
from test_source_guide_execution import controlled_app, http_client
from test_source_guide_updates import article_guidance, model_output, question_input

from knowledge_map.adapters.source_guides import SQLiteGuideStore
from knowledge_map.schemas.source_guides import SourceGuide


def test_startup_interrupts_accepted_search_that_stopped_before_model_entry(tmp_path):
    async def exercise():
        questions = []

        async def respond(messages, info):
            questions.append("unexpected model request")
            await asyncio.Event().wait()

        db_path = tmp_path / "guides.db"
        app = controlled_app(db_path, respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            response = await client.post(
                "/api/questions", json={"question": "Who backed AB 1 in 2025?"}
            )
            accepted = response.json()
            assert response.status_code == 202
            assert accepted["latest_attempt"]["status"] == "running"
        assert questions == []

        reopened = controlled_app(db_path, respond)
        async with (
            reopened.router.lifespan_context(reopened),
            http_client(reopened) as client,
        ):
            interrupted = (await client.get(response.headers["Location"])).json()
            assert interrupted["latest_attempt"]["status"] == "interrupted"
            assert interrupted["latest_attempt"]["outcome"] == "interrupted"
            assert interrupted["latest_attempt"]["message"] == (
                "This search was interrupted before it finished."
            )
            assert (
                interrupted["latest_attempt"]["attempt_id"]
                == (accepted["latest_attempt"]["attempt_id"])
            )
            assert (
                interrupted["latest_attempt"]["started_at"]
                == (accepted["latest_attempt"]["started_at"])
            )
            assert (
                interrupted["latest_attempt"]["finished_at"]
                >= (accepted["latest_attempt"]["started_at"])
            )
            for field in ("guide_id", "question", "created_at", "articles"):
                assert interrupted[field] == accepted[field]
            assert "last_retrieved_at" not in interrupted
            for _ in range(3):
                assert (
                    await client.get(response.headers["Location"])
                ).json() == interrupted
                assert (await client.get("/api/guides")).json()["guides"][0][
                    "latest_attempt"
                ] == interrupted["latest_attempt"]
                assert (await client.get("/")).status_code == 200
            assert questions == []

        restarted_again = controlled_app(db_path, respond)
        async with (
            restarted_again.router.lifespan_context(restarted_again),
            http_client(restarted_again) as client,
        ):
            assert (
                await client.get(response.headers["Location"])
            ).json() == interrupted
            assert questions == []

    asyncio.run(exercise())


def test_restarted_update_retries_without_losing_reading_or_accepting_old_results(
    tmp_path,
):
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        questions = []

        async def respond(messages, info):
            prompt = question_input(messages)
            if "question_policy" in prompt:
                questions.append(prompt["question"])
                if len(questions) > 1:
                    entered.set()
                    await release.wait()
                return model_output(info, {"status": "allowed"})
            if len(questions) == 2:
                raise RuntimeError("PRIVATE_PROVIDER_FAILURE")
            return model_output(
                info,
                article_guidance(
                    "Read the original housing provisions."
                    if len(questions) == 1
                    else "Read the revised housing provisions."
                ),
            )

        db_path = tmp_path / "guides.db"
        app = controlled_app(db_path, respond)
        async with app.router.lifespan_context(app), http_client(app) as client:
            first = await client.post(
                "/api/questions", json={"question": "Who backed AB 1 in 2025?"}
            )
            saved = (await completed_guide_async(client, first)).json()
            url = first.headers["Location"]
            update = await client.post(f"{url}/update", json={})
            assert update.status_code == 202
        assert questions == [saved["question"]]

        reopened = controlled_app(db_path, respond)
        async with (
            reopened.router.lifespan_context(reopened),
            http_client(reopened) as client,
        ):
            interrupted = (await client.get(url)).json()
            assert interrupted["latest_attempt"]["status"] == "interrupted"
            assert (
                interrupted["latest_attempt"]["attempt_id"]
                == (update.json()["latest_attempt"]["attempt_id"])
            )
            for field in (
                "guide_id",
                "question",
                "created_at",
                "articles",
                "assessment",
                "last_retrieved_at",
            ):
                assert interrupted[field] == saved[field]
            assert questions == [saved["question"]]
            retry = await client.post(f"{url}/update", json={})
            assert retry.status_code == 202
            await asyncio.wait_for(entered.wait(), 2)
            pending = (await client.get(url)).json()
            assert pending["latest_attempt"]["status"] == "running"
            assert (
                pending["latest_attempt"]["attempt_id"]
                != (interrupted["latest_attempt"]["attempt_id"])
            )
            assert pending["articles"] == saved["articles"]
            assert pending["last_retrieved_at"] == saved["last_retrieved_at"]
            assert (await client.post(f"{url}/update", json={})).status_code == 409
            store = SQLiteGuideStore(db_path)
            obsolete_result = SourceGuide(question=saved["question"], status="empty")
            store.finish(
                saved["guide_id"],
                interrupted["latest_attempt"]["attempt_id"],
                obsolete_result,
            )
            assert (await client.get(url)).json() == pending
            release.set()
            failed = (await completed_guide_async(client, retry)).json()
            assert failed["latest_attempt"]["status"] == "failed"
            assert failed["latest_attempt"]["outcome"] == "guidance_failed"
            assert failed["articles"] == saved["articles"]
            assert failed["last_retrieved_at"] == saved["last_retrieved_at"]
            assert "PRIVATE_PROVIDER_FAILURE" not in str(failed)

        restarted_again = controlled_app(db_path, respond)
        async with (
            restarted_again.router.lifespan_context(restarted_again),
            http_client(restarted_again) as client,
        ):
            assert (await client.get(url)).json() == failed
            assert questions == [saved["question"]] * 2
            entered.clear()
            release.clear()
            retry = await client.post(f"{url}/update", json={})
            assert retry.status_code == 202
            await asyncio.wait_for(entered.wait(), 2)
            pending = (await client.get(url)).json()
            assert pending["articles"] == saved["articles"]
            assert pending["last_retrieved_at"] == saved["last_retrieved_at"]
            for obsolete in (interrupted, failed):
                store.finish(
                    saved["guide_id"],
                    obsolete["latest_attempt"]["attempt_id"],
                    obsolete_result,
                )
                assert (await client.get(url)).json() == pending
            release.set()
            completed = (await completed_guide_async(client, retry)).json()
            for field in ("guide_id", "question", "created_at"):
                assert completed[field] == saved[field]
            assert (
                len(
                    {
                        guide["latest_attempt"]["attempt_id"]
                        for guide in (saved, interrupted, failed, completed)
                    }
                )
                == 4
            )
            assert completed["latest_attempt"]["status"] == "completed"
            assert completed["articles"][0]["reading_direction"] == (
                "Read the revised housing provisions."
            )
            assert completed["last_retrieved_at"] > saved["last_retrieved_at"]
            assert (
                completed["last_retrieved_at"]
                == (completed["latest_attempt"]["finished_at"])
            )
            for obsolete in (interrupted, failed):
                store.finish(
                    saved["guide_id"],
                    obsolete["latest_attempt"]["attempt_id"],
                    obsolete_result,
                )
                assert (await client.get(url)).json() == completed
            assert len((await client.get("/api/guides")).json()["guides"]) == 1
            assert questions == [saved["question"]] * 3

    asyncio.run(exercise())


def test_startup_preserves_terminal_guides_while_interrupting_unfinished_questions(
    tmp_path,
):
    async def exercise():
        questions = []
        assessments = {
            "Who backed AB 1?": {"status": "allowed"},
            "Who backed SB 2?": {"status": "allowed"},
            "Who will win?": {
                "status": "declined",
                "explanation": "Predictions are outside the question policy.",
            },
            "How did every member vote on AB 3?": {
                "status": "deferred",
                "explanation": "Complete roll calls are unavailable.",
                "recoverable_portion": "Reporting can identify some votes.",
            },
        }

        async def respond(messages, info):
            prompt = question_input(messages)
            if "question_policy" in prompt:
                questions.append(prompt["question"])
                return model_output(info, assessments[prompt["question"]])
            return model_output(
                info,
                {"source_notes": []}
                if questions[-1] == "Who backed SB 2?"
                else article_guidance("Read the reported votes."),
            )

        db_path = tmp_path / "guides.db"
        app = controlled_app(db_path, respond)
        saved = {}
        async with app.router.lifespan_context(app), http_client(app) as client:
            for question in assessments:
                response = await client.post(
                    "/api/questions", json={"question": question}
                )
                saved[response.headers["Location"]] = (
                    await completed_guide_async(client, response)
                ).json()
            assert [guide["status"] for guide in saved.values()] == [
                "completed",
                "empty",
                "declined",
                "completed",
            ]
            assert list(saved.values())[-1]["assessment"]["status"] == "deferred"
            pending = []
            for question in ("Who backed AB 4?", "Who backed AB 5?"):
                pending.append(
                    await client.post("/api/questions", json={"question": question})
                )
        assert questions == list(assessments)

        reopened = controlled_app(db_path, respond)
        async with (
            reopened.router.lifespan_context(reopened),
            http_client(reopened) as client,
        ):
            for url, guide in saved.items():
                assert (await client.get(url)).json() == guide
            for response in pending:
                guide = (await client.get(response.headers["Location"])).json()
                assert guide["latest_attempt"]["status"] == "interrupted"
                assert guide["question"] == response.json()["question"]
            assert len((await client.get("/api/guides")).json()["guides"]) == 6
            assert questions == list(assessments)

    asyncio.run(exercise())
