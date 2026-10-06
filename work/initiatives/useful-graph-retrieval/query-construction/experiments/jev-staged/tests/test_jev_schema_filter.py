"""Invented examples exercise the schema boundary without hosted or graph calls."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from knowledge_map.prototypes.atomic_deterministic_hydration import runner
from knowledge_map.prototypes.atomic_deterministic_hydration.jev_filtered_selector import (
    THRESHOLD,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.jev_schema_filter import (
    build_request,
    narrow_schema,
    normalize_decisions,
    schema_candidates,
)

from filtered_fragments import candidate_fragments, normalize_schema


class FakeJev:
    def __init__(self, scores=None, *, missing=None, error=None):
        self.scores = scores or {}
        self.missing = missing
        self.error = error
        self.calls = []

    def system_one(self, **request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return SimpleNamespace(
            nouls={
                key: SimpleNamespace(noul=self.scores.get(key, 0.02))
                for key in request["questions"]
                if key != self.missing
            },
            model="fake-jev",
            usage=SimpleNamespace(input_tokens=200, output_tokens=30),
        )


def test_filtered_selector_constructs_current_sdk_noul_criteria():
    from knowledge_map.prototypes.atomic_deterministic_hydration.contracts import (
        SemanticSchemaSelection,
    )
    from knowledge_map.prototypes.atomic_deterministic_hydration.jev_filtered_selector import (
        select_pieces,
    )

    client = FakeJev()
    result = select_pieces(client, "Which Bills?", SemanticSchemaSelection(
        labels=["Bill"], relationships=[], rationale="synthetic SDK contract check"
    ))
    assert result["ok"]
    assert len(client.calls) == 1
    for question in client.calls[0]["questions"].values():
        criteria = question.model_dump()["criteria"]
        assert criteria["true"] == "The whole fragment is required by the minimal semantic query."
        assert criteria["false"] == "The fragment is unnecessary or only related to the topic."


def fragment_ids(result):
    return {
        fragment.fragment_id
        for fragment in candidate_fragments(normalize_schema(result["output"]))
    }


def test_lobbying_endpoint_closure_preserves_complete_fragments():
    client = FakeJev({"relationship__LOBBIED_FOR": 0.9, "property__Bill__session": 0.8})
    result = narrow_schema(client, "Who lobbied for AB 9991 in the 2027 session?")
    assert result["ok"]
    assert result["output"]["labels"] == ["Bill", "LaborUnion", "Organization", "PAC"]
    assert result["output"]["filter_properties"] == {"Bill": ["session"]}
    assert result["closure"]["direct_label_selections"] == []
    assert "SINGLE__REL__ORGANIZATION__LOBBIED_FOR__BILL" in fragment_ids(result)
    assert "SINGLE__REL__PAC__LOBBIED_FOR__BILL" in fragment_ids(result)
    assert len(client.calls) == 1
    assert result["usage"]["total_tokens"] == 230
    assert result["threshold"] == 0.30
    assert THRESHOLD == 0.52


def test_vote_intermediate_path_survives_negative_label_judgments():
    result = narrow_schema(
        FakeJev({"relationship__VOTED_AYE": 0.95, "relationship__ACTION_ON": 0.85}),
        "Which politicians voted aye on AB 9991?",
    )
    assert result["output"]["labels"] == ["Bill", "LegislativeEvent", "Politician"]
    ids = fragment_ids(result)
    assert "SINGLE__REL__POLITICIAN__VOTED_AYE__LEGISLATIVEEVENT" in ids
    assert "SINGLE__REL__LEGISLATIVEEVENT__ACTION_ON__BILL" in ids


def test_property_judgment_retains_label_and_keeps_downstream_property_expansion():
    result = narrow_schema(
        FakeJev({"property__Bill__session": 0.30}), "Bills from 2027"
    )
    assert result["output"]["labels"] == ["Bill"]
    assert result["output"]["filter_properties"] == {"Bill": ["session"]}
    subgraph = normalize_schema(result["output"])
    assert "name" in subgraph.filterable_properties["Bill"]
    assert "session" in subgraph.filterable_properties["Bill"]
    assert result["decisions"]["property__Bill__session"]["selected_by_threshold"]


@pytest.mark.parametrize(
    "scores",
    [
        {"relationship__DISCUSSES_TOPIC": 0.9},
        {"property__Article__published_date": 0.9},
        {"property__Article__title": 0.9},
    ],
)
def test_article_semantics_preserve_compiler_owned_boundary(scores):
    result = narrow_schema(FakeJev(scores), "Reporting about housing during April 2027")
    assert result["ok"]
    assert "NewsArticle" not in result["output"]["labels"]
    assert "Article" not in result["output"]["labels"]
    assert result["closure"]["compiler_owned_article_required"]
    ids = fragment_ids(result)
    assert "CONTEXT__NEWSARTICLE" not in ids
    assert "ANCHOR__FILTER__ARTICLE__PUBLISHED_DATE__DATE_GTE" in ids
    if "relationship__DISCUSSES_TOPIC" in scores:
        assert "SINGLE__REL__ARTICLE__DISCUSSES_TOPIC__POLICYAREA" in ids
        assert "COMPLETE__AGG__POLICYAREA__COUNT_ARTICLE" in ids


def test_funded_keeps_all_endpoint_alternatives_visible():
    result = narrow_schema(
        FakeJev({"relationship__FUNDED": 0.9}), "Who funded the campaign?"
    )
    endpoints = schema_candidates()["relationship__FUNDED"]["valid_endpoints"]
    expected = {label for pair in endpoints for label in pair if label != "Article"}
    assert set(result["output"]["labels"]) == expected
    assert {item["label"] for item in result["closure"]["added_labels"]} == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"missing": "relationship__ACTION_ON"},
        {"error": RuntimeError("synthetic service failure")},
        {"scores": {"label__Bill": float("nan")}},
        {"scores": {"label__Bill": 1.1}},
    ],
)
def test_missing_invalid_and_service_failure_have_no_schema_output(kwargs):
    result = narrow_schema(FakeJev(**kwargs), "Bills introduced this year")
    assert not result["ok"]
    assert result["output"] is None
    assert result["normalization_errors"]
    assert result["latency_ms"] >= 0


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf")])
def test_bad_threshold_rejected_before_request(threshold):
    client = FakeJev()
    with pytest.raises(ValueError, match="threshold"):
        narrow_schema(client, "Bills", threshold=threshold)
    assert not client.calls


def test_decisions_must_cover_entire_vocabulary():
    with pytest.raises(ValueError, match="exactly cover"):
        normalize_decisions(schema_candidates(), {}, 0.3)


def test_request_is_one_multi_label_batch_with_no_graph_or_oracle_data():
    state, questions, captured = build_request("Which groups funded Cedar's campaign?")
    assert set(questions) == set(schema_candidates()) == set(captured)
    assert "label__NewsArticle" not in questions
    assert len(questions) == 36
    prompt = json.dumps({"state": state, "questions": captured})
    assert "verified-results" not in prompt
    assert "reference_answers" not in prompt
    assert "graph_rows" not in prompt
    assert all("true" in item["criteria"] for item in captured.values())


def test_jev_schema_failure_stops_before_selector_or_local_model(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No downstream or local model call is allowed after schema failure")

    monkeypatch.setattr(runner, "_agent_call", forbidden)
    monkeypatch.setattr(runner, "select_pieces_with_filtered_jev", forbidden)
    record = runner.run_case(
        SimpleNamespace(
            question="Who lobbied for AB 9991?",
            source_id="invented",
            opaque_id="sample",
        ),
        None,
        None,
        None,
        None,
        None,
        (),
        jev_client=FakeJev(missing="label__Bill"),
        selector_backend="jev-filtered",
        timeout=1,
        schema_filter_backend="jev",
    )
    assert record["failure_stage"] == "schema_filter"
    assert record["schema_filter_stage"]["call"]["decisions"]
    assert record["model_usage_by_stage"]["selector"]["requests"] == 0
    assert record["model_usage_by_stage"]["schema_filter"]["requests"] == 1
    assert not record["execution"]["ok"]
    assert runner._jev_telemetry([record])["requests"] == 0


def test_backend_default_keeps_local_filter_and_filtered_jev_selector(monkeypatch):
    local_calls = []
    selectors = []

    def local_call(agent, prompt):
        local_calls.append((agent, prompt))
        return {
            "ok": True,
            "output": {"labels": ["Bill"], "relationships": [], "rationale": "test"},
        }

    def selector(client, question, schema):
        selectors.append(schema)
        return {
            "ok": False,
            "output": None,
            "model_visible_prompt": "invented",
            "usage": {},
        }

    monkeypatch.setattr(runner, "_agent_call", local_call)
    monkeypatch.setattr(runner, "select_pieces_with_filtered_jev", selector)
    record = runner.run_case(
        SimpleNamespace(
            question="Which Bills?", source_id="invented", opaque_id="sample"
        ),
        None,
        "local-filter",
        None,
        None,
        None,
        (),
        jev_client=FakeJev(),
        selector_backend="jev-filtered",
        timeout=1,
    )
    assert record["schema_filter_stage"]["backend"] == "pydantic"
    assert len(local_calls) == len(selectors) == 1
    assert local_calls[0][0] == "local-filter"


@pytest.mark.parametrize("selector_backend", ["jev-filtered", "pydantic"])
def test_jev_backend_bypasses_local_filter_and_passes_closed_schema_to_selector(
    monkeypatch, selector_backend
):
    observed = []

    def selector(client, question, schema):
        observed.append(schema.model_dump(mode="json"))
        return {"ok": False, "model_visible_prompt": "invented", "usage": {}}

    def local_call(agent, prompt):
        assert selector_backend == "pydantic"
        assert agent == "local-selector"
        observed.append(
            json.loads(
                prompt.split("Semantic schema selection:\n")[1].split(
                    "\n\nSemantic piece catalog"
                )[0]
            )
        )
        return {"ok": False, "usage": {}}

    monkeypatch.setattr(runner, "select_pieces_with_filtered_jev", selector)
    monkeypatch.setattr(runner, "_agent_call", local_call)
    record = runner.run_case(
        SimpleNamespace(
            question="Who lobbied for AB 9991?",
            source_id="invented",
            opaque_id="sample",
        ),
        None,
        "must-not-run",
        "local-selector",
        None,
        None,
        (),
        jev_client=FakeJev({"relationship__LOBBIED_FOR": 0.9}),
        selector_backend=selector_backend,
        timeout=1,
        schema_filter_backend="jev",
    )
    assert observed
    assert all(item["relationships"] == ["LOBBIED_FOR"] for item in observed)
    assert all("Bill" in item["labels"] for item in observed)
    assert record["schema_filter_stage"]["backend"] == "jev"
    assert record["model_usage_by_stage"]["schema_filter"]["requests"] == 1
