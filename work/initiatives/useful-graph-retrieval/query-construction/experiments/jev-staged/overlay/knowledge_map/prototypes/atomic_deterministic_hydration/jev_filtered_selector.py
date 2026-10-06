"""PROTOTYPE: schema-pruned complete-fragment selector backed by Jev."""

# The batch adapter records client failures instead of aborting the experiment.
# ruff: noqa: BLE001

from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any

from filtered_fragments import (
    candidate_fragments,
    filter_attachment_rules,
    filter_prompt,
    normalize_schema,
    pruning_audit,
)
from fragment_selector import SELECTION_FIELDS
from pydantic import ValidationError
from typesafe_sdk import Noul, TypeSafeClient

from knowledge_map.prototypes.atomic_deterministic_hydration.contracts import (
    PieceSelection,
    SemanticSchemaSelection,
)

THRESHOLD = 0.52
GUIDANCE = (
    "Choose every complete semantic fragment required by the question and no others. "
    "The prior schema-filter stage has already limited the available entities and relationships. "
    "Relationship fragments imply all endpoints. Conditions imply their entity role. "
    "Property-condition decisions are independent of relationship variants. "
    "Stored-reporting joins and output formatting are automatic. Single and peer variants compete."
)


def _expand(
    fragments: tuple[Any, ...], scores: dict[str, float]
) -> dict[str, Any]:
    selected = [
        fragment
        for fragment in fragments
        if scores[fragment.fragment_id] >= THRESHOLD
        and fragment.competition_group is None
    ]
    groups = {
        fragment.competition_group
        for fragment in fragments
        if fragment.competition_group is not None
    }
    for group in groups:
        winner = max(
            (
                fragment
                for fragment in fragments
                if fragment.competition_group == group
            ),
            key=lambda fragment: scores[fragment.fragment_id],
        )
        if scores[winner.fragment_id] >= THRESHOLD:
            selected.append(winner)

    counts: dict[str, Counter[str]] = {
        field: Counter() for field in SELECTION_FIELDS
    }
    for fragment in selected:
        for field, ids in fragment.implications.items():
            incoming = Counter(ids)
            for piece_id, count in incoming.items():
                counts[field][piece_id] = max(counts[field][piece_id], count)
    selected_ids = sorted(fragment.fragment_id for fragment in selected)
    return {
        "threshold": THRESHOLD,
        "selected_fragment_ids": selected_ids,
        "selection": {
            field: [
                piece_id
                for piece_id, count in sorted(counts[field].items())
                for _ in range(count)
            ]
            for field in SELECTION_FIELDS
        },
        "filter_attachment_rules": filter_attachment_rules(fragments, selected_ids),
    }


def select_pieces(
    client: TypeSafeClient,
    question: str,
    schema_selection: SemanticSchemaSelection,
) -> dict[str, Any]:
    """Score schema-compatible semantic fragments and expand them into pieces."""

    schema = schema_selection.model_dump(mode="json")
    subgraph = normalize_schema(schema)
    fragments = candidate_fragments(subgraph)
    state = {
        "question": question,
        "schema_filter_output": schema,
        "normalized_query_subgraph": subgraph.public(),
        "selection_guidance": GUIDANCE,
    }
    questions: dict[str, Noul] = {}
    captured: dict[str, dict[str, Any]] = {}
    for index, fragment in enumerate(fragments, start=1):
        key = f"fragment_{index:03d}"
        instructions = filter_prompt(fragment) or fragment.prompt()
        criteria = {
            "true": "The whole fragment is required by the minimal semantic query.",
            "false": "The fragment is unnecessary or only related to the topic.",
        }
        questions[key] = Noul(instructions=instructions, criteria=criteria)
        captured[key] = {
            "fragment_id": fragment.fragment_id,
            "type": "noul",
            "instructions": instructions,
            "criteria": criteria,
        }

    model_visible_prompt = json.dumps(
        {"state": state, "questions": captured},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    started = time.perf_counter()
    try:
        response = client.system_one(state=state, questions=questions)
    except Exception as error:
        return {
            "ok": False,
            "error": {"type": type(error).__name__, "message": str(error)},
            "output": None,
            "decisions": {},
            "normalization_errors": ["Jev filtered-fragment selector call failed"],
            "usage": {"requests": 1},
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "model_visible_prompt": model_visible_prompt,
            "pruning": pruning_audit(subgraph, fragments),
        }

    errors: list[str] = []
    scores: dict[str, float] = {}
    decisions: dict[str, dict[str, Any]] = {}
    for index, fragment in enumerate(fragments, start=1):
        key = f"fragment_{index:03d}"
        answer = response.nouls.get(key)
        if answer is None:
            errors.append(f"missing Jev answer for {fragment.fragment_id}")
            continue
        score = float(answer.noul)
        scores[fragment.fragment_id] = score
        decisions[fragment.fragment_id] = {"score": score}

    expanded = None
    selection = None
    if not errors:
        expanded = _expand(fragments, scores)
        try:
            selection = PieceSelection.model_validate(expanded["selection"])
        except ValidationError as error:
            errors.extend(
                f"normalized PieceSelection: {item['loc']}: {item['msg']}"
                for item in error.errors()
            )

    usage = {
        "requests": 1,
        "input_tokens": response.usage.input_tokens or 0,
        "output_tokens": response.usage.output_tokens or 0,
        "total_tokens": (response.usage.input_tokens or 0)
        + (response.usage.output_tokens or 0),
    }
    return {
        "ok": selection is not None,
        "model": response.model,
        "output": (
            selection.model_dump(mode="json")
            if selection
            else expanded["selection"]
            if expanded
            else None
        ),
        "decisions": decisions,
        "normalization_errors": errors,
        "usage": usage,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "model_visible_prompt": model_visible_prompt,
        "pruning": pruning_audit(subgraph, fragments),
        "threshold": THRESHOLD,
        "selected_fragment_ids": (
            expanded["selected_fragment_ids"] if expanded else []
        ),
        "filter_attachment_rules": (
            expanded["filter_attachment_rules"] if expanded else []
        ),
    }
