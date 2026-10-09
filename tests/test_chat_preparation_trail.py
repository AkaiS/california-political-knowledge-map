"""Question assessment observations through direct submission."""

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from test_chat_session_trail import chat_capture as chat_capture  # noqa: PLC0414
from test_chat_web import guide_client, submit_guide


def scripted_model(outputs):
    outputs = iter(outputs)

    def respond(messages, info):
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, next(outputs))]
        )

    return FunctionModel(respond)


@pytest.mark.parametrize("status", ["allowed", "declined", "needs_edit", "deferred"])
def test_submitted_question_assessment_has_one_safe_observation(status, chat_capture):
    assessment = {"status": status}
    if status != "allowed":
        assessment["explanation"] = (
            "Name the bill." if status == "needs_edit" else "A stated limit."
        )
    if status == "deferred":
        assessment["recoverable_portion"] = "Available reporting."
    with guide_client(assessment=assessment) as (client, _, _):
        result = submit_guide(client, json={"question": "Who backed AB 1?"})
    assert result.status_code == 200
    spans = chat_capture.exported_spans_as_dict(parse_json_attributes=True)
    assessed = [s for s in spans if s["name"] == "chat_session.assessment"]
    assert len(assessed) == 1
    assert assessed[0]["attributes"]["status"] == status
    assert not any(
        s["name"] in {"chat_session.query_rewrite", "chat_session.approve"}
        for s in spans
    )
