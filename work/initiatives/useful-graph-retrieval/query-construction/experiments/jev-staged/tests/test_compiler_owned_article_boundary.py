"""Offline checks for the Jev article boundary and filter attachment."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from knowledge_map.prototypes.atomic_deterministic_hydration.compiler import (
    SemanticCompileError,
    compile_semantic,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.contracts import (
    ComposerWiring,
    PieceSelection,
    SemanticSchemaSelection,
    SemanticWiring,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.runner import (
    _composer_prompt,
    _deterministic_unique_wiring,
    _relationship_free_mode,
    _resolve_selection,
    _semantic_wiring_from_composer,
)

from filtered_fragments import (
    candidate_fragments,
    filter_attachment_rules,
    filter_prompt,
    normalize_schema,
)
from fragment_selector import SELECTION_FIELDS


def _selection(
    *,
    roles: tuple[str, ...] = (),
    relationships: tuple[str, ...] = (),
    filters: tuple[str, ...] = (),
    aggregations: tuple[str, ...] = (),
) -> PieceSelection:
    return PieceSelection(
        role_ids=list(roles),
        relationship_ids=list(relationships),
        filter_ids=list(filters),
        aggregation_ids=list(aggregations),
    )


def _compile(selection: PieceSelection):
    grouped, errors = _resolve_selection(selection)
    assert not errors
    wiring = _deterministic_unique_wiring(grouped)
    assert wiring is not None
    return grouped, compile_semantic(wiring, grouped)


def test_two_hop_claim_query_has_no_selectable_article_context() -> None:
    schema = SemanticSchemaSelection(
        labels=["Politician", "LegislativeEvent", "Bill"],
        relationships=["VOTED_AYE", "ACTION_ON"],
        rationale="A public official's recorded vote on a measure.",
    )
    fragments = candidate_fragments(normalize_schema(schema.model_dump(mode="json")))
    ids = {fragment.fragment_id for fragment in fragments}

    assert "CONTEXT__NEWSARTICLE" not in ids
    assert "SINGLE__REL__POLITICIAN__VOTED_AYE__LEGISLATIVEEVENT" in ids
    assert "SINGLE__REL__LEGISLATIVEEVENT__ACTION_ON__BILL" in ids
    assert all(
        "ROLE__NEWSARTICLE" not in implications
        for fragment in fragments
        for implications in fragment.implications.values()
    )


def test_explicit_reporting_lookup_uses_compiler_owned_context() -> None:
    grouped, errors = _resolve_selection(
        _selection(
            roles=("ROLE__POLITICIAN",),
            filters=("FILTER__POLITICIAN__NAME__EQ",),
        )
    )
    assert not errors
    assert _relationship_free_mode("What stored reporting mentions the official?") == (
        "shared_reporting"
    )
    wiring = _deterministic_unique_wiring(
        grouped, relationship_free_mode="shared_reporting"
    )
    assert wiring is not None
    compiled = compile_semantic(
        wiring, grouped, relationship_free_mode="shared_reporting"
    )
    assert "(_role_article:NewsArticle)-[:HAS_CHUNK]->(_role_chunk)" in compiled.cypher
    assert all(piece.piece_id != "COMPILER__ARTICLE_ROLE" for piece in grouped["role"])


@pytest.mark.parametrize(
    "extra_filters",
    (
        ("FILTER__ARTICLE__TITLE__EQ",),
        (
            "FILTER__ARTICLE__PUBLISHED_DATE__DATE_GTE",
            "FILTER__ARTICLE__PUBLISHED_DATE__DATE_LT",
        ),
    ),
)
def test_article_title_and_date_semantics_inject_internal_role(
    extra_filters: tuple[str, ...],
) -> None:
    grouped, compiled = _compile(
        _selection(
            roles=("ROLE__POLICYAREA",),
            relationships=("REL__ARTICLE__DISCUSSES_TOPIC__POLICYAREA",),
            filters=extra_filters,
        )
    )
    assert grouped["role"][0].piece_id == "COMPILER__ARTICLE_ROLE"
    assert "(role_0:NewsArticle)-[semantic_rel_0:DISCUSSES_TOPIC]->" in compiled.cypher


def test_article_topic_and_count_semantics_inject_internal_role() -> None:
    grouped, compiled = _compile(
        _selection(
            roles=("ROLE__POLICYAREA",),
            relationships=("REL__ARTICLE__DISCUSSES_TOPIC__POLICYAREA",),
            aggregations=("AGG__POLICYAREA__COUNT_ARTICLE",),
        )
    )
    assert grouped["role"][0].piece_id == "COMPILER__ARTICLE_ROLE"
    assert "count(DISTINCT role_0.id) AS article_count" in compiled.cypher


def test_composer_contract_cannot_emit_aggregate_wiring() -> None:
    assert "aggregate" not in ComposerWiring.model_json_schema()["properties"]
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ComposerWiring.model_validate(
            {
                "triples": [],
                "filters": [],
                "distinct_roles": [],
                "aggregate": None,
                "rationale": "The composer should not own aggregate selection.",
            }
        )


def test_non_aggregate_composition_has_no_aggregate_wiring() -> None:
    grouped, errors = _resolve_selection(
        _selection(
            roles=("ROLE__ORGANIZATION", "ROLE__BILL"),
            relationships=("REL__ORGANIZATION__LOBBIED_FOR__BILL",),
        )
    )
    assert not errors
    wiring = _semantic_wiring_from_composer(
        ComposerWiring(
            triples=[
                {
                    "relationship_index": 0,
                    "source_role_index": 0,
                    "target_role_index": 1,
                }
            ],
            filters=[],
            distinct_roles=[],
            rationale="Wire the selected lobbying relationship.",
        ),
        grouped,
    )
    assert wiring.aggregate is None


def test_selected_article_count_aggregate_is_wired_by_code() -> None:
    grouped, errors = _resolve_selection(
        _selection(
            roles=("ROLE__POLICYAREA",),
            relationships=("REL__ARTICLE__DISCUSSES_TOPIC__POLICYAREA",),
            aggregations=("AGG__POLICYAREA__COUNT_ARTICLE",),
        )
    )
    assert not errors
    wiring = _semantic_wiring_from_composer(
        ComposerWiring(
            triples=[
                {
                    "relationship_index": 0,
                    "source_role_index": 0,
                    "target_role_index": 1,
                }
            ],
            filters=[],
            distinct_roles=[],
            rationale="Wire article topics; code owns aggregation.",
        ),
        grouped,
    )
    assert wiring.aggregate is not None
    assert wiring.aggregate.model_dump() == {
        "aggregation_index": 0,
        "group_role_index": 1,
        "count_role_index": 0,
    }
    prompt = _composer_prompt(
        SimpleNamespace(question="How many articles discuss each policy area?"),
        grouped,
        [],
        None,
        None,
    )
    assert '"aggregation"' not in prompt
    assert "AGG__POLICYAREA__COUNT_ARTICLE" not in prompt


def test_unrelated_relationship_free_plan_fails_closed() -> None:
    grouped, errors = _resolve_selection(
        _selection(roles=("ROLE__POLITICIAN", "ROLE__LEGISLATIVEEVENT"))
    )
    assert not errors
    wiring = SemanticWiring(
        triples=[], filters=[], distinct_roles=[], aggregate=None, rationale="test"
    )
    with pytest.raises(SemanticCompileError, match="explicit shared-reporting"):
        compile_semantic(wiring, grouped)


def test_peer_independent_filter_attaches_to_anchor_role() -> None:
    schema = SemanticSchemaSelection(
        labels=["Organization", "Bill"],
        relationships=["LOBBIED_FOR"],
        rationale="Find other groups with the same recorded activity.",
    )
    fragments = candidate_fragments(normalize_schema(schema.model_dump(mode="json")))
    organization_filter = next(
        fragment
        for fragment in fragments
        if fragment.fragment_id == "ANCHOR__FILTER__ORGANIZATION__NAME__EQ"
    )
    prompt = filter_prompt(organization_filter)
    assert prompt is not None
    assert prompt["decision"] == (
        "Does the question specify a value that fixes or constrains Organization.name?"
    )
    assert "peer" not in prompt["decision"].lower()
    rules = filter_attachment_rules(
        fragments,
        (
            "PEER_SOURCE__REL__ORGANIZATION__LOBBIED_FOR__BILL",
            organization_filter.fragment_id,
        ),
    )
    assert rules == [
        {
            "filter_fragment_id": organization_filter.fragment_id,
            "entity": "Organization",
            "property": "name",
            "attachment": "the anchor role with this entity label; peer roles stay unrestricted",
        }
    ]


def test_implementation_contains_no_evaluation_case_hooks() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = (
        root / "filtered_fragments.py",
        root
        / "overlay/knowledge_map/prototypes/atomic_deterministic_hydration/catalog.py",
        root
        / "overlay/knowledge_map/prototypes/atomic_deterministic_hydration/compiler.py",
        root
        / "overlay/knowledge_map/prototypes/atomic_deterministic_hydration/jev_filtered_selector.py",
    )
    implementation = "\n".join(path.read_text() for path in paths)
    assert not re.search(r"\bQ\d{2}\b", implementation)
    assert "verified-results" not in implementation
    assert "Steve Hilton" not in implementation
    assert "SB 577" not in implementation
    assert SELECTION_FIELDS == (
        "role_ids",
        "relationship_ids",
        "filter_ids",
        "role_constraint_ids",
        "aggregation_ids",
    )
