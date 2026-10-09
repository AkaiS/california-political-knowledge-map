"""A guide attempt fixes its date while an explicit update starts a new session."""

import json
from datetime import UTC, datetime

from test_chat_web import completed_guide, guide_client, stored_article, submit_guide

from knowledge_map.core import chat


def test_guide_keeps_its_date_across_midnight_and_update_uses_a_new_date(
    monkeypatch, tmp_path
):
    initial = datetime(2026, 10, 1, 23, 59, tzinfo=UTC)
    after_midnight = datetime(2026, 10, 2, 0, 1, tzinfo=UTC)

    class Clock(datetime):
        current = initial

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(chat, "datetime", Clock)

    async def retrieve_across_midnight(fused):
        Clock.current = after_midnight
        return await stored_article(fused)

    question = "Which unions supported AB 1 in September 2026?"
    with guide_client(
        db_path=tmp_path / "guides.db",
        load_grounding=retrieve_across_midnight,
        guidance={
            "source_notes": [
                {
                    "source_article_id": "https://example.com/dense",
                    "note": "Read the section about union support for AB 1.",
                }
            ]
        },
    ) as (client, prompts, branches):
        first = submit_guide(client, json={"question": question}).json()
        url = f"/api/guides/{first['guide_id']}"
        assert first["status"] == "completed"
        assert client.get(url).json() == first
        assert len(prompts) == 2
        updated = completed_guide(client, client.post(f"{url}/update", json={})).json()

    assert updated["guide_id"] == first["guide_id"]
    assert updated["question"] == first["question"] == question
    assert updated["status"] == "completed"
    assert (
        updated["latest_attempt"]["attempt_id"] != first["latest_attempt"]["attempt_id"]
    )
    assert len(prompts) == 4
    for assessment, guidance, expected in (
        (prompts[0], prompts[1], initial),
        (prompts[2], prompts[3], after_midnight),
    ):
        assert json.loads(assessment[0])["question"] == question
        assert guidance[1] == question
        for request in (assessment, guidance):
            context = json.loads(request[0])
            assert context["as_of"] == expected.isoformat()
            assert context["current_date"] == expected.date().isoformat()
    for branch in branches.values():
        assert [request.rewrite.question for request, _ in branch.requests] == [
            question,
            question,
        ]
