"""Invented article-topic peers verify indexed wiring without live services."""

import copy

import pytest
from test_jev_staged_selector import Fake

from knowledge_map.jev import construction as runner
from knowledge_map.jev.compiler import (
    compile_semantic,
)
from knowledge_map.jev.contracts import (
    PieceSelection,
    SemanticSchemaSelection,
)
from knowledge_map.jev.jev_staged_selector import (
    select_pieces,
)


def article_peer():
    schema = SemanticSchemaSelection(
        labels=["PolicyArea"],
        relationships=["DISCUSSES_TOPIC"],
        filter_properties={"PolicyArea": ["name"]},
        rationale="Invented shared-article topic lookup",
    )
    client = Fake(
        {"PEER_TARGET__REL__ARTICLE__DISCUSSES_TOPIC__POLICYAREA"},
        properties={"property_1_FILTER__POLICYAREA__NAME__EQ"},
    )
    result = select_pieces(
        client, "Which other policy areas share articles with Topic {A} café?", schema
    )
    assert result["ok"]
    grouped, errors = runner._resolve_selection(
        PieceSelection.model_validate(result["output"]), allow_parent_roles=True
    )
    assert not errors
    return schema, client, result, grouped


def test_article_peers_keep_both_endpoints_and_anchor_filter():
    _, _, selection, grouped = article_peer()
    assert runner._deterministic_unique_wiring(grouped) is None
    wiring = runner._deterministic_staged_wiring(
        grouped, selection["filter_attachment_rules"][0]
    )
    assert wiring is not None
    assert [
        (edge.source_role_index, edge.target_role_index) for edge in wiring.triples
    ] == [(0, 1), (0, 2)]
    assert [item.role_index for item in wiring.filters] == [1]
    assert [
        (item.left_role_index, item.right_role_index) for item in wiring.distinct_roles
    ] == [(1, 2)]
    compiled = compile_semantic(wiring, grouped, allow_parent_distinct=True)
    assert len(compiled.wiring.triples) == 2
    assert len(compiled.slots) == 1


@pytest.mark.parametrize(
    "corruption", ["missing-edge", "wrong-endpoint", "wrong-filter", "wrong-distinct"]
)
def test_invalid_staged_article_attachments_fail_closed(corruption):
    _, _, selection, grouped = article_peer()
    attachment = copy.deepcopy(selection["filter_attachment_rules"][0])
    if corruption == "missing-edge":
        attachment["triples"].pop()
    elif corruption == "wrong-endpoint":
        attachment["triples"][0]["target_role_index"] = 0
    elif corruption == "wrong-filter":
        attachment["filters"][0]["role_index"] = 0
    else:
        attachment["distinct_roles"][0]["right_role_index"] = 1
    assert runner._deterministic_staged_wiring(grouped, attachment) is None
