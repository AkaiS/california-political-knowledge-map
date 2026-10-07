"""Invented staged-role cases verify attachment and subtype compiler contracts."""

import json
from types import SimpleNamespace

import pytest

from knowledge_map.jev import construction as runner
from knowledge_map.jev.compiler import (
    compile_semantic,
    validate_wiring,
)
from knowledge_map.jev.contracts import (
    SemanticSchemaSelection,
    SemanticWiring,
)
from knowledge_map.jev.filtered_fragments import candidate_fragments, normalize_schema
from knowledge_map.jev.jev_staged_selector import (
    make_role_plan,
    select_pieces,
)


class Answer(dict):
    def model_dump(self, **kwargs):
        return dict(self)


class Fake:
    def __init__(self, structural, scopes=None, properties=None, missing_stage=None):
        self.structural, self.scopes, self.properties = (
            structural,
            scopes or {},
            properties or set(),
        )
        self.calls, self.missing_stage = [], missing_stage

    def system_one(self, **request):
        self.calls.append(request)
        answers = {}
        for key, q in request["questions"].items():
            data = q.model_dump()
            if data["type"] == "choice":
                role = data["instructions"]["role"]
                choice = self.scopes.get(role["occurrence"], "unrestricted")
                answers[key] = Answer(
                    type="choice",
                    choice=choice,
                    confidence=0.9,
                    probabilities={
                        c: 0.97 if c == choice else 0.01 for c in data["criteria"]
                    },
                )
            else:
                yes = (
                    key in self.structural
                    if len(self.calls) == 1
                    else key in self.properties
                )
                answers[key] = Answer(type="noul", noul=0.99 if yes else 0.01)
        if self.missing_stage == len(self.calls):
            answers.pop(next(iter(answers)))
        return SimpleNamespace(
            answers=answers,
            model="fake",
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )


def schema():
    return SemanticSchemaSelection(
        labels=["Organization", "PAC", "LaborUnion", "Bill"],
        relationships=["LOBBIED_FOR"],
        rationale="invented",
    )


def test_general_organization_subtypes_never_add_roles():
    result = select_pieces(
        Fake({"SINGLE__REL__ORGANIZATION__LOBBIED_FOR__BILL"}),
        "Which organizations lobbied for AB 999?",
        schema(),
    )
    assert result["ok"], result
    assert result["output"]["role_ids"] == ["ROLE__BILL", "ROLE__ORGANIZATION"]
    assert len(result["output"]["relationship_ids"]) == 1
    assert not any("PAC" in key or "LABORUNION" in key for key in result["decisions"])
    assert [s["name"] for s in result["stages"]] == [
        "parent_structure",
        "role_subtypes",
        "role_properties",
    ]
    assert result["usage"]["requests"] == 3


def test_mixed_anchor_peer_refines_occurrences_and_preserves_distinctness():
    client = Fake(
        {"PEER_SOURCE__REL__ORGANIZATION__LOBBIED_FOR__BILL"},
        {0: "PAC", 1: "unrestricted"},
    )
    result = select_pieces(
        client,
        "Which organizations lobbied alongside the PAC named Sample Committee?",
        schema(),
    )
    assert result["ok"], result
    assert result["output"]["role_ids"] == [
        "ROLE__BILL",
        "ROLE__PAC",
        "ROLE__ORGANIZATION",
    ]
    assert set(result["output"]["relationship_ids"]) == {
        "REL__PAC__LOBBIED_FOR__BILL",
        "REL__ORGANIZATION__LOBBIED_FOR__BILL",
    }
    assert result["output"]["role_constraint_ids"] == ["DISTINCT__ORGANIZATION__ROLES"]
    selection = runner.PieceSelection.model_validate(result["output"])
    grouped, errors = runner._resolve_selection(selection, allow_parent_roles=True)
    assert not errors
    raw = result["filter_attachment_rules"][0]
    wiring = SemanticWiring.model_validate(
        {key: raw[key] for key in ("triples", "filters", "distinct_roles")}
        | {"aggregate": None, "rationale": "invented"}
    )
    assert validate_wiring(wiring, grouped)
    assert not validate_wiring(wiring, grouped, allow_parent_distinct=True)
    query = compile_semantic(wiring, grouped, allow_parent_distinct=True).cypher
    assert ":Organization:PAC" in query and "<>" in query


def test_filters_only_asked_for_selected_roles_and_cannot_add_person():
    expanded = schema().model_copy(update={"labels": [*schema().labels, "Politician"]})
    client = Fake({"SINGLE__REL__ORGANIZATION__LOBBIED_FOR__BILL"})
    result = select_pieces(client, "Organizations lobbying for AB 999", expanded)
    assert result["ok"]
    property_state = result["stages"][-1]
    assert all(
        q["instructions"]["selected_role"]["label"] != "Politician"
        for q in property_state["questions"].values()
    )
    assert "ROLE__POLITICIAN" not in result["output"]["role_ids"]


def test_aggregate_and_single_share_edge_context_and_relation_share_role():
    subgraph = normalize_schema(
        {
            "labels": ["PolicyArea"],
            "relationships": ["DISCUSSES_TOPIC"],
            "filter_properties": {},
        }
    )
    fragments = candidate_fragments(subgraph)
    ids = [
        "COMPLETE__AGG__POLICYAREA__COUNT_ARTICLE",
        "SINGLE__REL__ARTICLE__DISCUSSES_TOPIC__POLICYAREA",
        "CONTEXT__POLICYAREA",
    ]
    roles, edges, distinct = make_role_plan(fragments, ids)
    assert len(roles) == 2 and len(edges) == 1 and not distinct


@pytest.mark.parametrize("missing_stage", [1, 2, 3])
def test_missing_answer_preserves_attempt_and_stops(missing_stage):
    result = select_pieces(
        Fake(
            {"SINGLE__REL__ORGANIZATION__LOBBIED_FOR__BILL"},
            missing_stage=missing_stage,
        ),
        "Which organizations?",
        schema(),
    )
    assert not result["ok"] and result["output"] is None
    assert len(result["stages"]) == missing_stage
    assert result["usage"]["requests"] == missing_stage
    assert result["stages"][-1]["error"]
    assert json.loads(result["model_visible_prompt"])["stages"][-1]["questions"]


def test_true_property_attaches_existing_refined_role():
    client = Fake(
        {"PEER_SOURCE__REL__ORGANIZATION__LOBBIED_FOR__BILL"},
        {0: "PAC", 1: "unrestricted"},
        {"property_1_FILTER__ORGANIZATION__NAME__EQ"},
    )
    result = select_pieces(
        client, "Which organizations lobbied alongside PAC Sample Committee?", schema()
    )
    assert result["ok"], result
    assert result["output"]["filter_ids"] == ["FILTER__PAC__NAME__EQ"]
    assert result["filter_attachment_rules"][0]["filters"] == [
        {"filter_index": 0, "role_index": 1}
    ]
    assert len(result["output"]["role_ids"]) == 3


def test_uncertain_subtype_abstains_without_guessing_or_broadening():
    class Uncertain(Fake):
        def system_one(self, **request):
            response = super().system_one(**request)
            if any(
                q.model_dump()["type"] == "choice"
                for q in request["questions"].values()
            ):
                for answer in response.answers.values():
                    answer["choice"] = "PAC"
                    answer["probabilities"] = {
                        "PAC": 0.6,
                        "unrestricted": 0.2,
                        "LaborUnion": 0.1,
                        "unclear": 0.1,
                    }
            return response

    result = select_pieces(
        Uncertain({"SINGLE__REL__ORGANIZATION__LOBBIED_FOR__BILL"}),
        "Which organizations?",
        schema(),
    )
    assert not result["ok"]
    assert result["output"] is None
    assert result["abstention"]["choice"] == "PAC"


def test_union_refined_role_is_explicit_parent_compatible_mapping():
    data = schema().model_copy(
        update={"relationships": ["LOBBIED_FOR", "LOBBIED_AGAINST"]}
    )
    client = Fake(
        {"SINGLE__REL_ANY__ORGANIZATION__LOBBIED_FOR_OR_LOBBIED_AGAINST__BILL"},
        {0: "LaborUnion"},
    )
    result = select_pieces(client, "Which unions lobbied on AB 999?", data)
    assert result["ok"], result
    assert (
        result["filter_attachment_rules"][0]["role_plan"][-1]["label"] == "LaborUnion"
    )
    selection = runner.PieceSelection.model_validate(result["output"])
    grouped, errors = runner._resolve_selection(selection, allow_parent_roles=True)
    assert not errors
    raw = result["filter_attachment_rules"][0]
    wiring = SemanticWiring.model_validate(
        {key: raw[key] for key in ("triples", "filters", "distinct_roles")}
        | {"aggregate": None, "rationale": "union test"}
    )
    assert validate_wiring(wiring, grouped)
    assert not validate_wiring(wiring, grouped, allow_parent_distinct=True)


def test_parent_role_prompt_recognizes_anchors_and_shared_relationship_occurrence():
    from knowledge_map.jev.jev_staged_selector import (
        parent_role_prompt,
    )

    fragments = candidate_fragments(normalize_schema(schema().model_dump(mode="json")))
    for fragment in fragments:
        if not fragment.fragment_id.startswith("CONTEXT__"):
            continue
        prompt = parent_role_prompt(fragment)
        assert "named anchor" in prompt["decision"]
        assert "stored reporting" in prompt["decision"]
        assert "without a selectable" not in json.dumps(prompt)
        assert any("same occurrence" in rule for rule in prompt["rules"])
    ids = ["CONTEXT__ORGANIZATION", "SINGLE__REL__ORGANIZATION__LOBBIED_FOR__BILL"]
    roles, edges, _ = make_role_plan(fragments, ids)
    assert len(roles) == 2 and len(edges) == 1


@pytest.mark.parametrize(
    "choice,probability",
    [("PAC", 0.79), ("LaborUnion", 0.72), ("unrestricted", 0.60), ("unclear", 0.97)],
)
def test_uncertain_category_stops_before_properties_instead_of_broadening(
    choice, probability
):
    class Uncertain(Fake):
        def system_one(self, **request):
            result = super().system_one(**request)
            for value in result.answers.values():
                if value["type"] == "choice":
                    value["choice"] = choice
                    value["probabilities"] = {
                        key: probability if key == choice else (1 - probability) / 3
                        for key in value["probabilities"]
                    }
            return result

    client = Uncertain({"SINGLE__REL__ORGANIZATION__LOBBIED_FOR__BILL"})
    result = select_pieces(client, "Which organizations support AB 999?", schema())
    assert not result["ok"]
    assert result["output"] is None
    assert result["abstention"]["choice"] == choice
    assert result["abstention"]["stage"] == "role_subtypes"
    assert len(client.calls) == 2
    assert len(result["stages"]) == 2
    assert (
        result["stages"][-1]["decisions"]["scope_1"]["probabilities"][choice]
        == probability
    )


def test_campaign_decisions_compare_full_targets_and_named_entity_boundaries():
    from knowledge_map.jev.jev_staged_selector import (
        structural_prompt,
    )

    selected = SemanticSchemaSelection(
        labels=["Campaign", "Politician", "Prop"],
        relationships=["CAMPAIGN_FOR"],
        rationale="invented",
    )
    fragments = candidate_fragments(normalize_schema(selected.model_dump(mode="json")))
    prompts = [
        structural_prompt(f) for f in fragments if f.fragment_id.startswith("SINGLE__")
    ]
    assert len(prompts) == 2
    for prompt in prompts:
        assert set(prompt["target_alternatives"]) == {
            "Campaign -> Politician",
            "Campaign -> Prop",
        }
        assert any("named campaign" in rule for rule in prompt["rules"])
    context = next(f for f in fragments if f.fragment_id == "CONTEXT__POLITICIAN")
    prompt = structural_prompt(context)
    assert "separate query entity" in prompt["decision"]
    assert any("inside a campaign's name" in rule for rule in prompt["rules"])
