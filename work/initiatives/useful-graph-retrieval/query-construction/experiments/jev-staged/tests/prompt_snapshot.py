"""Capture synthetic rendered inputs in a fresh interpreter for parity checks."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace


def main():
    runtime = Path(sys.argv[1])
    sys.path[:0] = [str(runtime / "src"), str(runtime)]

    from knowledge_map.prototypes.atomic_deterministic_hydration import (
        jev_schema_filter as schema,
    )
    from knowledge_map.prototypes.atomic_deterministic_hydration import (
        jev_staged_selector as staged,
    )
    from knowledge_map.prototypes.atomic_deterministic_hydration import (
        runner,
    )
    from knowledge_map.prototypes.atomic_deterministic_hydration.contracts import (
        ComposerWiring,
        PieceSelection,
        SemanticSchemaSelection,
    )
    from test_jev_staged_selector import Fake

    import fragment_selector
    import peer_wording
    import reporting_keyword_gate
    from filtered_fragments import filter_attachment_rules, filter_prompt

    peer_wording.apply(runner, staged, fragment_selector)
    question = "Which other organizations share articles about Topic {A} café?"
    case = runner.Case(opaque_id="invented", source_id="invented", question=question)
    vocabulary = SemanticSchemaSelection(labels=["Organization", "Bill"], relationships=["LOBBIED_FOR"], rationale="synthetic")
    grouped, _ = runner._resolve_selection(PieceSelection(role_ids=["ROLE__ORGANIZATION", "ROLE__BILL"],
        relationship_ids=["REL__ORGANIZATION__LOBBIED_FOR__BILL"], filter_ids=["FILTER__BILL__NAME__EQ"]))
    state, questions, _ = schema.build_request(question)
    snapshot = {
        "agent_instructions": {name: getattr(runner, name) for name in ("FILTER_INSTRUCTIONS", "SELECTOR_INSTRUCTIONS", "COMPOSER_INSTRUCTIONS", "BINDER_INSTRUCTIONS")},
        "catalog": [piece.public() for piece in runner.CATALOG],
        "schema": {"state": state, "questions": {key: value.model_dump(mode="json") for key, value in questions.items()}},
        "fragments": {f.fragment_id: f.prompt() for f in fragment_selector.FRAGMENTS},
        "structural": {f.fragment_id: staged.structural_prompt(f) for f in fragment_selector.FRAGMENTS},
        "filters": {f.fragment_id: filter_prompt(f) for f in fragment_selector.FRAGMENTS},
        "attachments": filter_attachment_rules(fragment_selector.FRAGMENTS, fragment_selector.BY_FRAGMENT_ID),
        "gate": {"decision": reporting_keyword_gate.GATE_DECISION, "criteria": reporting_keyword_gate.GATE_CRITERIA},
        "filter_request": runner._filter_prompt(case),
        "selector_requests": [runner._selector_prompt(case, vocabulary, feedback) for feedback in (None, {"errors": ["Invented {error}"]})],
        "composer_requests": [runner._composer_prompt(case, grouped, [{"synthetic": "{data}"}], previous, {"errors": ["Invented {error}"]})
                              for previous in (None, ComposerWiring(triples=[], filters=[], distinct_roles=[], rationale="synthetic"))],
        "binder_requests": [runner._binding_prompt(case, SimpleNamespace(slots=[SimpleNamespace(description="Invented {slot} café", value_type="string", allowed_values=["{A}", "B"])]), feedback)
                            for feedback in (None, {"failures": ["Invented {error}"]})],
        "staged_requests": [],
    }
    for fragments, properties in [({"SINGLE__REL__ORGANIZATION__LOBBIED_FOR__BILL"}, set()),
                                 ({"PEER_SOURCE__REL__ORGANIZATION__LOBBIED_FOR__BILL"}, {"property_1_FILTER__ORGANIZATION__NAME__EQ"})]:
        client = Fake(fragments, properties=properties)
        result = staged.select_pieces(client, question, vocabulary)
        assert result["ok"]
        snapshot["staged_requests"].append([
            {"state": request["state"], "questions": {key: value.model_dump(mode="json") for key, value in request["questions"].items()}}
            for request in client.calls
        ])
    # Exercise the actual retry branch so instructions nested in feedback are
    # compared too, rather than only testing caller-supplied feedback values.
    retry_requests = []
    original_call, original_filter = runner._agent_call, runner.narrow_schema

    def failed_selection(agent, prompt):
        retry_requests.append(prompt)
        return {"ok": False, "usage": {}, "latency_ms": 0}

    try:
        runner._agent_call = failed_selection
        runner.narrow_schema = lambda *args, **kwargs: {
            "ok": True, "output": vocabulary.model_dump(mode="json"),
            "model_visible_prompt": "synthetic schema", "usage": {}, "latency_ms": 0,
        }
        result = runner.run_case(case, None, None, None, None, None, (),
                                 jev_client=SimpleNamespace(), selector_backend="pydantic",
                                 schema_filter_backend="jev", timeout=1)
        assert result["failure_stage"] == "selector"
        assert len(retry_requests) == 3
        assert '"instruction"' in retry_requests[1]
        snapshot["selector_retry_requests"] = retry_requests
    finally:
        runner._agent_call, runner.narrow_schema = original_call, original_filter
    print(json.dumps(snapshot, sort_keys=True))


if __name__ == "__main__":
    main()
