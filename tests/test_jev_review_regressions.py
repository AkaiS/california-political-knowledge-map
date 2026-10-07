"""PR review cases exercise conjunctions, reporting constraints, and binding scope."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from neo4j import Driver
from test_jev_staged_selector import Answer, Fake

from knowledge_map.jev.binding import (
    build_binding_contract,
    validate_and_resolve_bindings,
)
from knowledge_map.jev.compiler import compile_semantic, validate_wiring
from knowledge_map.jev.construction import (
    _binding_prompt,
    _deterministic_staged_wiring,
    _resolve_selection,
)
from knowledge_map.jev.contracts import PieceSelection, SemanticSchemaSelection
from knowledge_map.jev.jev_staged_selector import select_pieces
from knowledge_map.jev.validation import Case


def selected_wiring(result):
    assert result["ok"], result["normalization_errors"]
    grouped, errors = _resolve_selection(
        PieceSelection.model_validate(result["output"]), allow_parent_roles=True
    )
    assert not errors
    wiring = _deterministic_staged_wiring(grouped, result["filter_attachment_rules"][0])
    assert wiring is not None
    assert not validate_wiring(wiring, grouped, allow_parent_distinct=True)
    return grouped, wiring


class Parallel(Fake):
    def __init__(
        self,
        separate=True,
        uncertain=False,
        union=False,
        logic="conjunction",
        separate_side="target",
    ):
        super().__init__(
            {
                "SINGLE__REL__ORGANIZATION__LOBBIED_FOR__BILL",
                "SINGLE__REL__ORGANIZATION__LOBBIED_AGAINST__BILL",
            },
            properties={
                "property_0_FILTER__BILL__NAME__EQ",
                "property_2_FILTER__BILL__NAME__EQ",
            },
        )
        self.separate, self.uncertain = separate, uncertain
        self.separate_side = separate_side
        self.logic = logic
        if union:
            self.structural.add(
                "SINGLE__REL_ANY__ORGANIZATION__LOBBIED_FOR_OR_LOBBIED_AGAINST__BILL"
            )

    def system_one(self, **request):
        if any(
            "union" in q.model_dump()["instructions"]
            for q in request["questions"].values()
        ):
            self.calls.append(request)
            return SimpleNamespace(
                answers={
                    key: Answer(
                        type="choice",
                        choice=self.logic,
                        probabilities={
                            c: 0.98 if c == self.logic else 0.01
                            for c in q.model_dump()["criteria"]
                        },
                    )
                    for key, q in request["questions"].items()
                },
                model="fake",
                usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            )
        if not any(key.startswith("occurrence_") for key in request["questions"]):
            return super().system_one(**request)
        self.calls.append(request)
        answers = {}
        for key, question in request["questions"].items():
            choices = question.model_dump()["criteria"]
            choice = f"{self.separate_side}_separate" if self.separate else "shared"
            if self.uncertain:
                choice = "unclear"
            answers[key] = Answer(
                type="choice",
                choice=choice,
                probabilities={c: 0.98 if c == choice else 0.01 for c in choices},
            )
        return SimpleNamespace(
            answers=answers,
            model="fake",
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )


def parallel_schema():
    return SemanticSchemaSelection(
        labels=["Organization", "Bill"],
        relationships=["LOBBIED_FOR", "LOBBIED_AGAINST"],
        rationale="Two independently required predicates",
    )


@pytest.mark.parametrize("union", [False, True])
def test_conjunction_keeps_both_predicates_and_distinct_bill_anchors(union):
    result = select_pieces(
        Parallel(union=union),
        "Which organizations lobbied for AB 186 and against SB 1947?",
        parallel_schema(),
    )
    grouped, wiring = selected_wiring(result)
    assert len(grouped["relationship"]) == 2
    assert len(grouped["role"]) == 3
    assert len({t.source_role_index for t in wiring.triples}) == 1
    assert len({t.target_role_index for t in wiring.triples}) == 2
    assert len(wiring.distinct_roles) == 1
    compiled = compile_semantic(wiring, grouped, allow_parent_distinct=True)
    assert ":LOBBIED_FOR]" in compiled.cypher and ":LOBBIED_AGAINST]" in compiled.cypher
    assert "role_0.name = $parameter_0" in compiled.cypher
    assert "role_2.name = $parameter_1" in compiled.cypher
    assert "role_0.id <> role_2.id" in compiled.cypher
    assert compiled.binding_pattern.relationships == [
        {
            "source_variable": "role_1",
            "predicates": ["LOBBIED_AGAINST"],
            "target_variable": "role_0",
        },
        {
            "source_variable": "role_1",
            "predicates": ["LOBBIED_FOR"],
            "target_variable": "role_2",
        },
    ]
    contract = build_binding_contract(MagicMock(spec=Driver), compiled.binding_pattern)
    prompt = _binding_prompt(
        Case("multi", "multi", "Organizations lobbying for AB 186 and against SB 1947"),
        contract,
        None,
        pattern=compiled.binding_pattern,
    )
    payload = json.loads(
        prompt.split("Binding slots and semantic relationships:\n", 1)[1]
    )
    assert payload["slots"][0]["semantic_relationships"][0]["predicates"] == [
        "LOBBIED_AGAINST"
    ]
    assert payload["slots"][1]["semantic_relationships"][0]["predicates"] == [
        "LOBBIED_FOR"
    ]
    expected_stages = [
        "parent_structure",
        "role_occurrences",
        "role_subtypes",
        "role_properties",
    ]
    if union:
        expected_stages.insert(1, "predicate_logic")
    assert [s["name"] for s in result["stages"]] == expected_stages


def test_alternative_predicates_keep_only_the_union_and_one_bill():
    result = select_pieces(
        Parallel(union=True, logic="alternatives"),
        "Which organizations lobbied for or against AB 186?",
        parallel_schema(),
    )
    grouped, wiring = selected_wiring(result)
    assert len(grouped["relationship"]) == 1
    assert len(grouped["role"]) == 2
    assert (
        ":LOBBIED_FOR|LOBBIED_AGAINST]"
        in compile_semantic(wiring, grouped, allow_parent_distinct=True).cypher
    )
    assert "role_occurrences" not in [s["name"] for s in result["stages"]]


def test_uncertain_predicate_logic_stops_without_selecting_an_operator():
    result = select_pieces(
        Parallel(union=True, logic="unclear"),
        "Which organizations lobbied on the bills?",
        parallel_schema(),
    )
    assert not result["ok"]
    assert result["output"] is None
    assert result["stages"][-1]["name"] == "predicate_logic"


def test_same_bill_across_predicates_stays_shared():
    result = select_pieces(
        Parallel(separate=False),
        "Which organizations both lobbied for and against AB 186?",
        parallel_schema(),
    )
    grouped, wiring = selected_wiring(result)
    assert len(grouped["role"]) == 2
    assert len(wiring.triples) == 2
    assert len({t.target_role_index for t in wiring.triples}) == 1
    assert not wiring.distinct_roles


def test_distinct_organizations_can_share_one_bill_across_predicates():
    client = Parallel(separate_side="source")
    client.properties.clear()
    result = select_pieces(
        client,
        "Which different organizations lobbied for and against AB 186?",
        parallel_schema(),
    )
    grouped, wiring = selected_wiring(result)
    assert len(grouped["role"]) == 3
    assert len({t.source_role_index for t in wiring.triples}) == 2
    assert len({t.target_role_index for t in wiring.triples}) == 1
    assert len(wiring.distinct_roles) == 1
    compiled = compile_semantic(wiring, grouped, allow_parent_distinct=True)
    assert "role_1.id <> role_2.id" in compiled.cypher


def test_uncertain_endpoint_identity_stops_without_merging_conditions():
    result = select_pieces(
        Parallel(uncertain=True),
        "Which organizations lobbied for and against these bills?",
        parallel_schema(),
    )
    assert not result["ok"]
    assert result["output"] is None
    assert result["stages"][-1]["name"] == "role_occurrences"


def publication_stance():
    schema = SemanticSchemaSelection(
        labels=["Organization", "Bill"],
        relationships=["DECLARED_STANCE"],
        filter_properties={"Article": ["published_date"]},
        rationale="Claims supported by July reporting",
    )
    result = select_pieces(
        Fake(
            {"SINGLE__REL__ORGANIZATION__DECLARED_STANCE__BILL"},
            properties={
                "property_0_FILTER__BILL__NAME__EQ",
                "property_2_FILTER__ARTICLE__PUBLISHED_DATE__DATE_GTE",
                "property_2_FILTER__ARTICLE__PUBLISHED_DATE__DATE_LT",
            },
        ),
        "Which organizations have a recorded position on AB 1018, reported in July 2026?",
        schema,
    )
    return selected_wiring(result)


def test_publication_constraints_filter_claim_evidence_articles():
    grouped, wiring = publication_stance()
    compiled = compile_semantic(wiring, grouped, allow_parent_distinct=True)
    query = compiled.cypher
    assert (
        "MATCH (_article_0:NewsArticle)-[:HAS_CHUNK]->(_chunk_0)\nWHERE date(substring(_article_0.published_date,0,10)) >= date($parameter_1) AND date(substring(_article_0.published_date,0,10)) < date($parameter_2)"
        in query
    )
    assert "role_0" not in query
    assert len(compiled.slots) == 3
    assert {n.label.value for n in compiled.binding_pattern.nodes} == {
        "NewsArticle",
        "Organization",
        "Bill",
    }


def test_reporting_article_exception_does_not_allow_disconnected_entities():
    from knowledge_map.jev.catalog import BY_ID

    grouped, wiring = publication_stance()
    grouped["role"].append(BY_ID["ROLE__POLITICIAN"])
    assert (
        "every selected role must belong to the connected semantic pattern"
        in validate_wiring(wiring, grouped, allow_parent_distinct=True)
    )


def test_publication_window_applies_independently_to_each_claim_article():
    client = Parallel()
    client.properties.update(
        {
            "property_3_FILTER__ARTICLE__PUBLISHED_DATE__DATE_GTE",
            "property_3_FILTER__ARTICLE__PUBLISHED_DATE__DATE_LT",
        }
    )
    schema = parallel_schema().model_copy(
        update={"filter_properties": {"Article": ["published_date"]}}
    )
    result = select_pieces(
        client,
        "Organizations lobbying for AB 186 and against SB 1947, reported in July 2026",
        schema,
    )
    grouped, wiring = selected_wiring(result)
    query = compile_semantic(wiring, grouped, allow_parent_distinct=True).cypher
    for index in (0, 1):
        assert (
            f"date(substring(_article_{index}.published_date,0,10)) >= date($parameter_2)"
            in query
        )
        assert (
            f"date(substring(_article_{index}.published_date,0,10)) < date($parameter_3)"
            in query
        )


@pytest.mark.parametrize("session_first", [False, True])
def test_canonical_session_scopes_bill_lookup_regardless_of_slot_order(session_first):
    from knowledge_map.jev.catalog import BY_ID
    from knowledge_map.jev.contracts import SemanticWiring

    grouped, _ = _resolve_selection(
        PieceSelection(
            role_ids=["ROLE__BILL"],
            filter_ids=["FILTER__BILL__NAME__EQ", "FILTER__BILL__SESSION__EQ"],
        )
    )
    wiring = SemanticWiring(
        triples=[],
        filters=[
            {"filter_index": 0, "role_index": 0},
            {"filter_index": 1, "role_index": 0},
        ],
        distinct_roles=[],
        aggregate=None,
        rationale="Named bill in one session",
    )
    assert grouped["role"][0] == BY_ID["ROLE__BILL"]
    compiled = compile_semantic(
        wiring, grouped, relationship_free_mode="shared_reporting"
    )
    driver = MagicMock(spec=Driver)
    scopes = []

    def run(query, parameters=None):
        if "RETURN DISTINCT toString(n.id)" in str(query):
            scopes.append(parameters)
            return (
                [{"id": "Bill:2025-2026:ab-186", "value": "AB 186"}]
                if parameters == {"scope_session": "2025-2026"}
                else []
            )
        return [{"value": "2025-2026"}]

    driver.session.return_value.__enter__.return_value.run.side_effect = run
    contract = build_binding_contract(driver, compiled.binding_pattern)
    if session_first:
        contract.slots.reverse()
    normalized, feedback = validate_and_resolve_bindings(
        driver,
        contract,
        {"parameter_0": "AB 186", "parameter_1": "2025–2026"},
        compiled.binding_pattern,
    )
    assert feedback["valid"]
    assert normalized == {"parameter_0": "AB 186", "parameter_1": "2025-2026"}
    assert scopes == [{"scope_session": "2025-2026"}]
