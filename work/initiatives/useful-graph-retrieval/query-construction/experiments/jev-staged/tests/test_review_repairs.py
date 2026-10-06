"""Invented article-topic peers verify indexed wiring without live services."""

import copy
from types import SimpleNamespace

import pytest
from knowledge_map.prototypes.atomic_deterministic_hydration import runner
from knowledge_map.prototypes.atomic_deterministic_hydration.compiler import (
    compile_semantic,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.contracts import (
    PieceSelection,
    SemanticSchemaSelection,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.jev_staged_selector import (
    select_pieces,
)
from test_jev_staged_selector import Fake


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
    result = select_pieces(client, "Which other policy areas share articles with Topic {A} café?", schema)
    assert result["ok"]
    grouped, errors = runner._resolve_selection(PieceSelection.model_validate(result["output"]), allow_parent_roles=True)
    assert not errors
    return schema, client, result, grouped


def test_article_peers_keep_both_endpoints_and_anchor_filter():
    _, _, selection, grouped = article_peer()
    assert runner._deterministic_unique_wiring(grouped) is None
    wiring = runner._deterministic_staged_wiring(grouped, selection["filter_attachment_rules"][0])
    assert wiring is not None
    assert [(edge.source_role_index, edge.target_role_index) for edge in wiring.triples] == [(0, 1), (0, 2)]
    assert [item.role_index for item in wiring.filters] == [1]
    assert [(item.left_role_index, item.right_role_index) for item in wiring.distinct_roles] == [(1, 2)]
    compiled = compile_semantic(wiring, grouped, allow_parent_distinct=True)
    assert len(compiled.wiring.triples) == 2
    assert len(compiled.slots) == 1


@pytest.mark.parametrize("corruption", ["missing-edge", "wrong-endpoint", "wrong-filter", "wrong-distinct"])
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


def test_article_peers_reach_binding_and_execution_without_composer(monkeypatch):
    schema, _, selection, _ = article_peer()
    case = runner.Case(opaque_id="synthetic-article-peer", source_id="invented", question="Which other policy areas share articles with Topic A?")
    calls = []
    monkeypatch.setattr(runner, "narrow_schema", lambda *args, **kwargs: {
        "ok": True, "output": schema.model_dump(mode="json"),
        "model_visible_prompt": "synthetic schema", "usage": {}, "latency_ms": 0,
    })
    monkeypatch.setattr(runner, "select_pieces_with_staged_jev", lambda *args: selection)
    monkeypatch.setattr(runner, "_abstract_cyver", lambda *args: {"errors": [], "authorized_abstract_structure": True})

    def unexpected_composer(*args):
        pytest.fail("Compiler-owned article wiring must not call the composer")

    monkeypatch.setattr(runner, "_agent_call", unexpected_composer)

    def bind(model, driver, request, compiled, **kwargs):
        calls.append(("bind", compiled.wiring))
        return {"valid": True, "normalized_resolved_bindings": {"p0": "invented"}, "attempts": []}

    monkeypatch.setattr(runner, "_bind_positional", bind)
    monkeypatch.setattr(runner, "validate_plan", lambda *args: {"authorized": True})

    def execute(driver, plan, timeout):
        calls.append(("execute", plan))
        return {"ok": True, "rows": [{"invented": "peer"}], "error": None, "latency_ms": 0}

    monkeypatch.setattr(runner, "_execute", execute)
    record = runner.run_case(case, None, None, None, None, None, (), jev_client=SimpleNamespace(),
                             selector_backend="jev-staged", schema_filter_backend="jev", timeout=1)
    assert record["failure_stage"] is None
    assert record["composition_stage"]["composer_call_count"] == 0
    assert [stage for stage, _ in calls] == ["bind", "execute"]
    assert len(calls[0][1].triples) == 2
