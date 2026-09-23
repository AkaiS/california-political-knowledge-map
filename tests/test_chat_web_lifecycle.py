"""Session lifetime at POST /api/chat and the application lifespan boundary.

Injected sessions return public outcomes. Weak references observe their release
without depending on the active registry's representation.
"""

import asyncio
import gc
import logging
import weakref
from contextlib import asynccontextmanager, nullcontext

import httpx
import pytest
from starlette.testclient import TestClient
from test_chat_web import events, no_dependencies, question_request
from test_chat_web_answers import AnswerSession, answer, approval_request
from test_chat_web_corrections import (
    CorrectionSession,
    correction_request,
    rejection_request,
)

from knowledge_map.schemas.query_preparation import (
    AwaitingQueryApproval,
    DeclinedQuestion,
    QueryApproval,
    RewriteUnavailable,
)
from knowledge_map.schemas.retrieval import EvidenceAssemblyFailure
from knowledge_map.web import create_app


@pytest.mark.parametrize(
    "outcome",
    [
        DeclinedQuestion(message="Predictions are outside the question policy."),
        RewriteUnavailable(message="The Query Rewriter is unavailable."),
    ],
)
def test_terminal_preparation_releases_the_session_and_cannot_start_a_second_question(
    outcome,
):
    created = []

    def session_factory(question, dependencies):
        session = CorrectionSession([outcome])
        created.append(weakref.ref(session))
        return session

    with TestClient(
        create_app(startup=no_dependencies, session_factory=session_factory),
        base_url="http://localhost",
    ) as client:
        completed = events(
            client.post("/api/chat", json=question_request("Who will win?"))
        )
        assert outcome.message in "".join(
            event["delta"] for event in completed if event["type"] == "text-delta"
        )
        gc.collect()
        assert created[0]() is None
        later = client.post("/api/chat", json=question_request("Who supported AB 2?"))
        assert later.status_code == 409
        assert later.json() == {"error": "Start a new chat to ask a question."}
        assert len(created) == 1


@pytest.mark.parametrize("phase", ["prepare", "approve", "approval_start"])
def test_interrupted_session_cannot_resume_or_retain_its_question(phase):
    async def exercise():
        entered = asyncio.Event()
        created = []

        class WaitingSession(AnswerSession):
            async def prepare(self):
                if phase == "prepare":
                    entered.set()
                    await asyncio.Event().wait()
                return await super().prepare()

            async def approve(self):
                entered.set()
                await asyncio.Event().wait()
                return await super().approve()

        def session_factory(question, dependencies):
            session = WaitingSession()
            created.append(weakref.ref(session))
            return session

        app = create_app(startup=no_dependencies, session_factory=session_factory)

        async def interrupted_app(scope, receive, send):
            async def forward(message):
                if (
                    phase == "approval_start"
                    and message["type"] == "http.response.body"
                    and b"Search details" in message.get("body", b"")
                ):
                    entered.set()
                    await asyncio.Event().wait()
                await send(message)

            await app(scope, receive, forward)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=interrupted_app),
            base_url="http://localhost",
        ) as client:
            payload = question_request("Who backed AB 1?")
            if phase != "prepare":
                prepared = events(await client.post("/api/chat", json=payload))
                payload = approval_request(prepared)
            pending = asyncio.create_task(client.post("/api/chat", json=payload))
            await asyncio.wait_for(entered.wait(), timeout=2)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            del pending
            await asyncio.sleep(0)
            later = await client.post(
                "/api/chat", json=question_request("Who backed AB 2?")
            )
            assert later.status_code == 409
            assert later.json() == {"error": "Start a new chat to ask a question."}
            gc.collect()
            assert created[0]() is None
            assert len(created) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "state", ["pending_approval", "awaiting_correction", "answered"]
)
@pytest.mark.parametrize("shutdown_fails", [False, True])
def test_restart_releases_sessions_and_cannot_resume_browser_history(
    state, shutdown_fails
):
    created = []

    def session_factory(question, dependencies):
        session = AnswerSession()
        created.append(weakref.ref(session))
        return session

    @asynccontextmanager
    async def startup():
        yield None
        if shutdown_fails:
            raise RuntimeError("shutdown failed")

    app = create_app(startup=startup, session_factory=session_factory)
    with (
        pytest.raises(RuntimeError, match="shutdown failed")
        if shutdown_fails
        else nullcontext(),
        TestClient(app, base_url="http://localhost") as client,
    ):
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        history = approval_request(prepared)
        if state == "awaiting_correction":
            events(client.post("/api/chat", json=rejection_request(prepared)))
            history = correction_request(prepared, "I meant AB 2.")
        elif state == "answered":
            completed = events(client.post("/api/chat", json=history))
            history["messages"][-1]["parts"] = [
                {"type": "text", "text": event["delta"]}
                for event in completed
                if event["type"] == "text-delta"
            ]
            history["messages"].extend(question_request("Who backed AB 2?")["messages"])
        else:
            gc.collect()
            assert created[0]() is not None
    gc.collect()
    assert created[0]() is None

    with TestClient(
        create_app(startup=no_dependencies, session_factory=session_factory),
        base_url="http://localhost",
    ) as restarted:
        later = restarted.post("/api/chat", json=history)
        assert later.status_code == 409
        assert later.json() == {"error": "Start a new chat to ask a question."}
        assert len(created) == 1
        fresh = events(
            restarted.post(
                "/api/chat",
                json=question_request("Who backed AB 2?", "new-conversation"),
            )
        )
        assert any(event["type"] == "tool-approval-request" for event in fresh)
        assert len(created) == 2


def test_conversations_cannot_exchange_approvals_corrections_or_answers():
    created = {}

    def session_factory(question, dependencies):
        session = CorrectionSession(
            [
                AwaitingQueryApproval(approval=QueryApproval(question=question)),
                AwaitingQueryApproval(
                    approval=QueryApproval(question=f"Revised: {question}")
                ),
            ]
        )
        session.outcome = answer().model_copy(
            update={"introduction": f"Selected reporting for {question}"}
        )
        created[question] = weakref.ref(session)
        return session

    with TestClient(
        create_app(startup=no_dependencies, session_factory=session_factory),
        base_url="http://localhost",
    ) as client:
        proposals = {}
        for question in ("AB 1", "AB 2"):
            proposals[question] = events(
                client.post("/api/chat", json=question_request(question, question))
            )
        foreign_approval = approval_request(proposals["AB 1"], conversation_id="AB 2")
        assert client.post("/api/chat", json=foreign_approval).status_code == 409
        for question, prepared in proposals.items():
            rejected = rejection_request(prepared)
            rejected["id"] = question
            events(client.post("/api/chat", json=rejected))
            gc.collect()
            assert created[question]() is not None

        foreign_correction = correction_request(proposals["AB 1"], "Only labor unions.")
        foreign_correction["id"] = "AB 2"
        assert client.post("/api/chat", json=foreign_correction).status_code == 409

        for question, prepared in proposals.items():
            correction = correction_request(prepared, "Only labor unions.")
            correction["id"] = question
            revised = events(client.post("/api/chat", json=correction))
            assert next(
                event["input"]
                for event in revised
                if event["type"] == "tool-input-available"
            ) == {"question": f"Revised: {question}"}
            completed = events(
                client.post(
                    "/api/chat",
                    json=approval_request(revised, conversation_id=question),
                )
            )
            text = "".join(
                event["delta"] for event in completed if event["type"] == "text-delta"
            )
            assert text == (
                f"Selected reporting for {question}\n\nNo passages were selected."
            )
            gc.collect()
            assert created[question]() is None


@pytest.mark.parametrize(
    "outcome",
    [answer(), EvidenceAssemblyFailure(execution=answer().evidence.execution)],
)
def test_answer_completion_releases_the_session_and_requires_a_new_conversation(
    outcome,
):
    created = []

    def session_factory(question, dependencies):
        session = AnswerSession(outcome)
        created.append(weakref.ref(session))
        return session

    with TestClient(
        create_app(startup=no_dependencies, session_factory=session_factory),
        base_url="http://localhost",
    ) as client:
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        payload = approval_request(prepared)
        events(client.post("/api/chat", json=payload))
        gc.collect()
        assert created[0]() is None
        payload["messages"].extend(question_request("Who supported AB 2?")["messages"])
        for later_payload in (payload, question_request("Who supported AB 2?")):
            later = client.post("/api/chat", json=later_payload)
            assert later.status_code == 409
            assert later.json() == {"error": "Start a new chat to ask a question."}
        assert len(created) == 1

        fresh = events(
            client.post(
                "/api/chat",
                json=question_request("Who supported AB 2?", "conversation-2"),
            )
        )
        assert any(event["type"] == "tool-approval-request" for event in fresh)
        assert len(created) == 2


@pytest.mark.parametrize("phase", ["prepare", "approve", "reject", "revised_prepare"])
def test_unrecoverable_session_failure_is_safe_terminal_and_releases_the_session(
    phase, caplog
):
    created = []

    class FailingSession(CorrectionSession):
        async def prepare(self):
            if phase == "prepare" or (phase == "revised_prepare" and self.corrections):
                raise RuntimeError("PRIVATE_FAILURE_DIAGNOSTIC")
            return await super().prepare()

        def reject(self, correction=None):
            if phase == "reject":
                raise RuntimeError("PRIVATE_FAILURE_DIAGNOSTIC")
            return super().reject(correction)

        async def approve(self):
            raise RuntimeError("PRIVATE_FAILURE_DIAGNOSTIC")

    def session_factory(question, dependencies):
        session = FailingSession(
            [AwaitingQueryApproval(approval=QueryApproval(question="Who backed AB 1?"))]
        )
        created.append(weakref.ref(session))
        return session

    # Pytest's captured tracebacks would otherwise retain the failed session.
    with (
        caplog.at_level(logging.CRITICAL, logger="knowledge_map.web"),
        TestClient(
            create_app(startup=no_dependencies, session_factory=session_factory),
            base_url="http://localhost",
        ) as client,
    ):
        response = client.post("/api/chat", json=question_request("Who backed AB 1?"))
        if phase != "prepare":
            prepared = events(response)
            if phase == "approve":
                response = client.post("/api/chat", json=approval_request(prepared))
            else:
                events(client.post("/api/chat", json=rejection_request(prepared)))
                response = client.post(
                    "/api/chat",
                    json=correction_request(prepared, "I meant AB 2."),
                )
        completed = events(response)
        assert completed[-1] == {"type": "finish", "finishReason": "stop"}
        assert "Start a new chat to ask a question." in response.text
        assert "PRIVATE_FAILURE_DIAGNOSTIC" not in response.text
        if phase == "approve":
            operation = next(
                event
                for event in completed
                if event.get("toolName") == "Search details"
            )
            assert any(
                event["type"] == "tool-output-error"
                and event["toolCallId"] == operation["toolCallId"]
                for event in completed
            )
        gc.collect()
        assert created[0]() is None
        later = client.post("/api/chat", json=question_request("Who backed AB 2?"))
        assert later.status_code == 409
        assert later.json() == {"error": "Start a new chat to ask a question."}
        assert len(created) == 1
