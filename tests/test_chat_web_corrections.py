"""Editing means submitting another complete question without implicit history."""

import json

from test_chat_web import guide_client, submit_guide


def test_edited_complete_question_is_assessed_and_retrieved_independently():
    with guide_client() as (client, prompts, branches):
        first = submit_guide(client, json={"question": "Who backed AB 1?"}).json()
        second = submit_guide(
            client, json={"question": "Who backed SB 2 in 2025?"}
        ).json()
        assert first["guide_id"] != second["guide_id"]
        assert client.get(f"/api/guides/{first['guide_id']}").json() == first
    assert first["question"] == "Who backed AB 1?"
    assert second["question"] == "Who backed SB 2 in 2025?"
    assert json.loads(prompts[2][0])["question"] == "Who backed SB 2 in 2025?"
    assert "AB 1" not in json.dumps(prompts[2])
    for branch in branches.values():
        assert [request.rewrite.question for request, _ in branch.requests] == [
            first["question"],
            second["question"],
        ]
