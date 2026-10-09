"""The application owns shared dependencies across independent searches."""

from contextlib import asynccontextmanager

from starlette.testclient import TestClient
from test_chat_web import submit_guide

from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.web import create_app


def test_application_opens_and_closes_dependencies_once_for_several_questions():
    lifecycle = []

    @asynccontextmanager
    async def startup():
        lifecycle.append("started")
        yield None
        lifecycle.append("closed")

    class Session:
        chat_session_id = "test-session"

        async def run(self):
            return QuestionAssessment(status="needs_edit", explanation="Name the bill.")

    with TestClient(
        create_app(startup=startup, session_factory=lambda *_: Session()),
        base_url="http://localhost",
    ) as client:
        for _ in range(2):
            assert (
                submit_guide(client, json={"question": "Who backed that bill?"}).json()[
                    "status"
                ]
                == "needs_edit"
            )
        assert lifecycle == ["started"]
    assert lifecycle == ["started", "closed"]
