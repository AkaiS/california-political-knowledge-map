"""Reporting intent decisions fail closed and remain isolated between requests."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_jev_staged_selector import Answer

from knowledge_map.jev import reporting
from knowledge_map.jev.contracts import SemanticSchemaSelection
from knowledge_map.jev.jev_schema_filter import (
    narrow_schema,
    normalize_decisions,
    schema_candidates,
)


class GateClient:
    def __init__(self, probability):
        self.probability = probability

    def system_one(self, **kwargs):
        answers = (
            {}
            if self.probability is None
            else {reporting.GATE_KEY: Answer(type="noul", noul=self.probability)}
        )
        return SimpleNamespace(
            answers=answers,
            model="synthetic-jev",
            usage=SimpleNamespace(input_tokens=2, output_tokens=1),
        )


@pytest.fixture
def selected_roles(monkeypatch):
    selection = {
        "ok": True,
        "output": {"role_ids": ["ROLE__POLITICIAN"], "relationship_ids": []},
        "refined_role_plan": {"roles": [{"label": "Politician"}], "edges": []},
        "normalization_errors": [],
        "stages": [],
        "usage": {"requests": 0},
    }
    monkeypatch.setattr(
        reporting.staged, "select_pieces", lambda *args: deepcopy(selection)
    )
    return SemanticSchemaSelection(
        labels=["Politician"], relationships=[], rationale="Invented reporting lookup."
    )


@pytest.mark.parametrize("probability", [None, float("nan"), 1.5])
def test_missing_or_invalid_reporting_decision_stops_selection(
    selected_roles, probability
):
    result = reporting.select_pieces(
        GateClient(probability), "Find stored reporting.", selected_roles
    )
    assert not result["ok"]
    assert result["relationship_free_mode"] == "forbidden"
    assert result["output"] is None


def test_simultaneous_identical_questions_keep_their_own_reporting_decisions(
    selected_roles,
):
    async def exercise():
        results = await asyncio.gather(
            *(
                asyncio.to_thread(
                    reporting.select_pieces,
                    GateClient(probability),
                    "Same question.",
                    selected_roles,
                )
                for probability in (0.99, 0.01)
            )
        )
        assert [r["relationship_free_mode"] for r in results] == [
            "shared_reporting",
            "forbidden",
        ]
        assert all(r["ok"] for r in results)

    asyncio.run(exercise())


def test_schema_closure_preserves_all_relationship_endpoints_without_choosing_roles():
    candidates = schema_candidates()
    scores = {
        key: 0.99 if key == "relationship__DECLARED_STANCE" else 0.01
        for key in candidates
    }
    selection, audit = normalize_decisions(candidates, scores, 0.8)
    assert selection.relationships == ["DECLARED_STANCE"]
    assert "Organization" in selection.labels
    assert "Bill" in selection.labels
    assert audit["closure"]["added_labels"]


def test_schema_missing_answer_stops_before_role_selection():
    class MissingSchema:
        def system_one(self, **kwargs):
            return SimpleNamespace(
                nouls={},
                model="synthetic-jev",
                usage=SimpleNamespace(input_tokens=2, output_tokens=1),
            )

    result = narrow_schema(MissingSchema(), "A concrete question.", threshold=0.8)
    assert not result["ok"]
    assert result["output"] is None
