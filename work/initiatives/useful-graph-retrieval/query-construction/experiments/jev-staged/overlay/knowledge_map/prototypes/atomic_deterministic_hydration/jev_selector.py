"""PROTOTYPE: Jev occurrence-count selector for the atomic piece catalog."""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import ValidationError
from typesafe_sdk import Choice, TypeSafeClient

from knowledge_map.prototypes.atomic_deterministic_hydration.catalog import (
    CATALOG,
    Piece,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.contracts import (
    PieceSelection,
    SemanticSchemaSelection,
)

_FIELD_BY_KIND = {
    "role": "role_ids",
    "relationship": "relationship_ids",
    "filter": "filter_ids",
    "role_constraint": "role_constraint_ids",
    "aggregation": "aggregation_ids",
}

_COUNT_CRITERIA = {
    "zero": "The question does not require this semantic piece.",
    "one": "The question requires exactly one occurrence of this semantic piece.",
    "two": "The question requires exactly two occurrences of this semantic piece.",
    "three_or_more": "The question requires three or more occurrences of this semantic piece.",
}

_BINARY_CRITERIA = {
    "zero": "The question does not require this semantic piece.",
    "one": "The question requires this semantic piece once.",
}


def _question(piece: Piece) -> tuple[Choice, dict[str, Any]]:
    criteria = (
        _BINARY_CRITERIA
        if piece.kind in {"role_constraint", "aggregation"}
        else _COUNT_CRITERIA
    )
    instructions = {
        "task": "Choose how many occurrences of this compiler-owned semantic piece the question requires.",
        "piece_id": piece.piece_id,
        "piece": piece.public(),
        "rules": [
            "Count semantic roles, relationships, filters, constraints, and aggregates only.",
            "Reporting context, provenance, result fields, parameters, and Cypher are automatic.",
            "Choose zero when the piece is merely related to the topic but is not needed to answer the question.",
        ],
    }
    return (
        Choice(instructions=instructions, criteria=criteria),
        {"type": "choice", "instructions": instructions, "criteria": criteria},
    )


def select_pieces(
    client: TypeSafeClient,
    question: str,
    schema_selection: SemanticSchemaSelection,
) -> dict[str, Any]:
    """Ask one independent occurrence-count Choice for every catalog piece."""

    state = {
        "question": question,
        "semantic_schema_selection": schema_selection.model_dump(mode="json"),
        "instruction": (
            "Produce a complete semantic piece multiset for the question. "
            "Each supplied Choice concerns one piece and is evaluated independently."
        ),
    }
    questions: dict[str, Choice] = {}
    captured_questions: dict[str, dict[str, Any]] = {}
    for piece in CATALOG:
        choice, captured = _question(piece)
        questions[piece.piece_id] = choice
        captured_questions[piece.piece_id] = captured

    model_visible_prompt = json.dumps(
        {"state": state, "questions": captured_questions},
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
            "normalization_errors": ["Jev selector call failed"],
            "usage": {"requests": 1},
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "model_visible_prompt": model_visible_prompt,
        }

    selected: dict[str, list[str]] = {
        "role_ids": [],
        "relationship_ids": [],
        "filter_ids": [],
        "role_constraint_ids": [],
        "aggregation_ids": [],
    }
    decisions: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for piece in CATALOG:
        answer = response.choices.get(piece.piece_id)
        if answer is None:
            errors.append(f"missing Jev answer for {piece.piece_id}")
            continue
        decisions[piece.piece_id] = {
            "choice": answer.choice,
            "probabilities": dict(answer.probabilities),
            "confidence": answer.confidence,
        }
        if answer.choice == "three_or_more":
            errors.append(
                f"{piece.piece_id} selected unsupported occurrence count three_or_more"
            )
            continue
        count = {"zero": 0, "one": 1, "two": 2}.get(answer.choice)
        if count is None:
            errors.append(
                f"{piece.piece_id} returned unknown occurrence count {answer.choice!r}"
            )
            continue
        selected[_FIELD_BY_KIND[piece.kind]].extend([piece.piece_id] * count)

    selection = None
    if not errors:
        try:
            selection = PieceSelection.model_validate(selected)
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
        "output": selection.model_dump(mode="json") if selection else selected,
        "decisions": decisions,
        "normalization_errors": errors,
        "usage": usage,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "model_visible_prompt": model_visible_prompt,
    }
