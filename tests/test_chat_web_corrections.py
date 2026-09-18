"""Query Rewrite corrections observed through the local chat ASGI protocol."""

from starlette.testclient import TestClient
from test_chat_web import events, no_dependencies, question_request
from test_chat_web_answers import AnswerSession, approval_request

from knowledge_map.schemas.query_preparation import (
    AwaitingQueryApproval,
    QueryApproval,
    RewriteRejection,
)
from knowledge_map.web import create_app


def rejection_request(preparation):
    request = approval_request(preparation)
    request["messages"][-1]["parts"][0]["approval"]["approved"] = False
    return request


def correction_request(preparation, correction):
    request = rejection_request(preparation)
    request["messages"][-1]["parts"][0]["state"] = "output-denied"
    request["messages"].append(
        {
            "id": f"correction-{preparation[0]['messageId']}",
            "role": "user",
            "parts": [{"type": "text", "text": correction}],
        }
    )
    return request


class CorrectionSession(AnswerSession):
    def __init__(self, proposals):
        super().__init__()
        self.proposals = iter(proposals)
        self.corrections = []

    async def prepare(self):
        return next(self.proposals)

    def reject(self, correction=None):
        self.corrections.append(correction)
        return RewriteRejection(
            question="The rejected question", relational=True, correction=correction
        )


def test_rejection_asks_for_a_correction_without_rejecting_or_retrieving_yet():
    session = AnswerSession()
    with TestClient(
        create_app(startup=no_dependencies, session_factory=lambda *_: session),
        base_url="http://localhost",
    ) as client:
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        rejected = events(client.post("/api/chat", json=rejection_request(prepared)))
        stale_approval = client.post("/api/chat", json=approval_request(prepared))

    assert [event["type"] for event in rejected] == [
        "start",
        "tool-output-denied",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]
    assert rejected[0]["messageId"] == prepared[0]["messageId"]
    assert rejected[1]["toolCallId"] == prepared[4]["toolCallId"]
    assert "Describe the change you want in your next message." in "".join(
        event["delta"] for event in rejected if event["type"] == "text-delta"
    )
    assert stale_approval.status_code == 409
    assert session.approvals == 0


def test_repeated_corrections_prepare_new_public_proposals_before_separate_approval():
    questions = []
    session = CorrectionSession(
        [
            AwaitingQueryApproval(
                approval=QueryApproval(question="Which organizations supported AB 1?")
            ),
            AwaitingQueryApproval(
                approval=QueryApproval(question="Which labor unions opposed AB 1?")
            ),
            AwaitingQueryApproval(
                approval=QueryApproval(
                    question="How did legislators vote on AB 1?",
                    explanation="Complete roll calls are unavailable.",
                    recoverable_portion="Reporting can identify some votes.",
                )
            ),
        ]
    )

    def session_factory(question, dependencies):
        questions.append(question)
        return session

    with TestClient(
        create_app(startup=no_dependencies, session_factory=session_factory),
        base_url="http://localhost",
    ) as client:
        prepared = events(
            client.post("/api/chat", json=question_request("Who backed AB 1?"))
        )
        for index, (correction, expected_approval) in enumerate(
            [
                (
                    "I meant labor unions that opposed it.",
                    {"question": "Which labor unions opposed AB 1?"},
                ),
                (
                    "How did legislators vote on AB 1?",
                    {
                        "question": "How did legislators vote on AB 1?",
                        "explanation": "Complete roll calls are unavailable.",
                        "recoverable_portion": "Reporting can identify some votes.",
                    },
                ),
            ]
        ):
            events(client.post("/api/chat", json=rejection_request(prepared)))
            assert len(session.corrections) == index
            previous_approval = approval_request(prepared)
            revised = events(
                client.post("/api/chat", json=correction_request(prepared, correction))
            )
            assert session.corrections[-1] == correction
            assert session.approvals == 0
            assert not any(
                event.get("toolName") == "Search details" for event in revised
            )
            proposal = next(
                event for event in revised if event["type"] == "tool-input-available"
            )
            assert proposal["input"] == expected_approval
            assert proposal["toolCallId"] != prepared[4]["toolCallId"]
            assert any(event["type"] == "tool-approval-request" for event in revised)
            assert client.post("/api/chat", json=previous_approval).status_code == 409
            prepared = revised

        events(client.post("/api/chat", json=approval_request(prepared)))

    assert questions == ["Who backed AB 1?"]
    assert session.corrections == [
        "I meant labor unions that opposed it.",
        "How did legislators vote on AB 1?",
    ]
    assert session.approvals == 1
