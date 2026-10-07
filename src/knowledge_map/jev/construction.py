# ruff: noqa: BLE001
import json
import time
from collections import Counter
from typing import Any

from knowledge_map.core.bill_sessions import parse_bill_designation
from knowledge_map.jev.catalog import BY_ID, COMPILER_NEWS_ARTICLE_ROLE, Piece
from knowledge_map.jev.compiler import SemanticCompileError, validate_wiring
from knowledge_map.jev.contracts import (
    AggregateWiring,
    ComposerWiring,
    DistinctRoleWiring,
    FilterWiring,
    PieceSelection,
    SemanticWiring,
    TripleWiring,
)
from knowledge_map.jev.topology import ConstraintOperator, NodeLabel, PropertyName
from knowledge_map.jev.validation import (
    Case,
    QueryPlan,
    _jsonable,
    deterministic_errors,
)
from knowledge_map.prompts import load_prompt


def _resolve_selection(
    selection: PieceSelection,
    *,
    allow_parent_roles: bool = False,
) -> tuple[dict[str, list[Piece]], list[str]]:
    ids = {
        "role": selection.role_ids,
        "relationship": selection.relationship_ids,
        "filter": selection.filter_ids,
        "role_constraint": selection.role_constraint_ids,
        "aggregation": selection.aggregation_ids,
    }
    grouped = {kind: [] for kind in ids}
    errors = []
    for expected_kind, piece_ids in ids.items():
        for piece_id in piece_ids:
            piece = BY_ID.get(piece_id)
            if piece is None:
                errors.append(f"unknown piece id: {piece_id}")
            elif piece.kind != expected_kind:
                errors.append(f"{piece_id} belongs in {piece.kind}_ids")
            else:
                grouped[expected_kind].append(piece)
    needs_article = (
        any(
            piece.source_label == NodeLabel.NEWS_ARTICLE
            or piece.target_label == NodeLabel.NEWS_ARTICLE
            for piece in grouped["relationship"]
        )
        or any(
            piece.node_label == NodeLabel.NEWS_ARTICLE for piece in grouped["filter"]
        )
        or any(
            piece.group_label == NodeLabel.NEWS_ARTICLE
            or piece.count_label == NodeLabel.NEWS_ARTICLE
            for piece in grouped["aggregation"]
        )
    )
    if needs_article:
        grouped["role"].insert(0, COMPILER_NEWS_ARTICLE_ROLE)
    date_filters = [
        piece
        for piece in grouped["filter"]
        if piece.property == PropertyName.PUBLISHED_DATE
    ]
    if date_filters and {piece.operator for piece in date_filters} != {
        ConstraintOperator.DATE_GTE,
        ConstraintOperator.DATE_LT,
    }:
        errors.append("a publication date range needs both boundary filter IDs")
    role_counts = Counter(piece.node_label for piece in grouped["role"])
    if allow_parent_roles:
        role_counts[NodeLabel.ORGANIZATION] += (
            role_counts[NodeLabel.PAC] + role_counts[NodeLabel.LABOR_UNION]
        )
    for piece in grouped["relationship"]:
        required = Counter((piece.source_label, piece.target_label))
        for label, count in required.items():
            if role_counts[label] < count:
                errors.append(
                    f"{piece.piece_id} needs {count} selected {label.value} role occurrence(s)"
                )
    for piece in grouped["filter"]:
        if role_counts[piece.node_label] < 1:
            errors.append(
                f"{piece.piece_id} needs a selected {piece.node_label.value} role"
            )
    grouped["role_constraint"] = [
        piece
        for piece in grouped["role_constraint"]
        if role_counts[piece.node_label] >= 2
    ]
    for piece in grouped["aggregation"]:
        if role_counts[piece.group_label] < 1 or role_counts[piece.count_label] < 1:
            errors.append(
                f"{piece.piece_id} needs selected {piece.group_label.value} and {piece.count_label.value} roles"
            )
    return grouped, list(dict.fromkeys(errors))


def _composer_prompt(
    case: Case,
    grouped: dict[str, list[Piece]],
    filter_attachment_rules: list[dict[str, str]],
    previous: ComposerWiring | None,
    feedback: dict[str, Any] | None,
) -> str:
    safe = {
        kind: [piece.public() for piece in grouped[kind]]
        for kind in ("role", "relationship", "filter", "role_constraint")
    }
    prompt = load_prompt("jev-staged/runner-composer-prompt-01", version=1).format(
        value_0=case.question
    ) + json.dumps(safe, indent=2)
    if filter_attachment_rules:
        prompt += load_prompt(
            "jev-staged/runner-composer-prompt-02", version=1
        ) + json.dumps(filter_attachment_rules, indent=2)
    if previous is not None:
        prompt += (
            load_prompt("jev-staged/runner-composer-prompt-04", version=1)
            + previous.model_dump_json(indent=2)
            + load_prompt("jev-staged/runner-composer-prompt-03", version=1)
            + json.dumps(feedback, indent=2)
        )
    return prompt


def _deterministic_aggregate_wiring(
    grouped: dict[str, list[Piece]],
) -> AggregateWiring | None:
    aggregates = grouped["aggregation"]
    if not aggregates:
        return None
    if len(aggregates) != 1:
        raise SemanticCompileError(
            "deterministic aggregate wiring needs exactly one selected aggregate"
        )
    aggregate = aggregates[0]
    roles = grouped["role"]
    group_matches = [
        index
        for index, role in enumerate(roles)
        if role.node_label == aggregate.group_label
    ]
    count_matches = [
        index
        for index, role in enumerate(roles)
        if role.node_label == aggregate.count_label
    ]
    if len(group_matches) != 1:
        raise SemanticCompileError(
            f"selected aggregate needs exactly one {aggregate.group_label.value} group role"
        )
    if len(count_matches) != 1:
        raise SemanticCompileError(
            f"selected aggregate needs exactly one {aggregate.count_label.value} count role"
        )
    return AggregateWiring(
        aggregation_index=0,
        group_role_index=group_matches[0],
        count_role_index=count_matches[0],
    )


def _semantic_wiring_from_composer(
    composer_wiring: ComposerWiring,
    grouped: dict[str, list[Piece]],
) -> SemanticWiring:
    """Add compiler-owned aggregate wiring to the model's bounded output."""

    return SemanticWiring(
        triples=composer_wiring.triples,
        filters=composer_wiring.filters,
        distinct_roles=composer_wiring.distinct_roles,
        aggregate=_deterministic_aggregate_wiring(grouped),
        rationale=composer_wiring.rationale,
    )


def _deterministic_staged_wiring(
    grouped: dict[str, list[Piece]],
    attachment: dict[str, Any],
    *,
    relationship_free_mode: str = "forbidden",
) -> SemanticWiring | None:
    """Keep repeated article endpoints and property anchors at their selected indexes."""
    try:
        candidate = SemanticWiring(
            triples=attachment["triples"],
            filters=attachment["filters"],
            distinct_roles=attachment["distinct_roles"],
            aggregate=_deterministic_aggregate_wiring(grouped),
            rationale="Deterministic assembly from staged occurrence attachments.",
        )
    except (KeyError, ValueError):
        return None
    return (
        candidate
        if not validate_wiring(
            candidate,
            grouped,
            relationship_free_mode=relationship_free_mode,
            allow_parent_distinct=True,
        )
        else None
    )


def _deterministic_unique_wiring(
    grouped: dict[str, list[Piece]],
    *,
    relationship_free_mode: str = "forbidden",
) -> SemanticWiring | None:
    roles = grouped["role"]

    def unique(label: NodeLabel | None) -> int | None:
        matches = [
            index for index, role in enumerate(roles) if role.node_label == label
        ]
        return matches[0] if len(matches) == 1 else None

    triples = []
    for index, piece in enumerate(grouped["relationship"]):
        source = unique(piece.source_label)
        target = unique(piece.target_label)
        if source is None or target is None:
            return None
        triples.append(
            TripleWiring(
                relationship_index=index,
                source_role_index=source,
                target_role_index=target,
            )
        )
    filters = []
    for index, piece in enumerate(grouped["filter"]):
        role = unique(piece.node_label)
        if role is None:
            return None
        filters.append(FilterWiring(filter_index=index, role_index=role))
    distinct = []
    for index, piece in enumerate(grouped["role_constraint"]):
        matches = [
            i for i, role in enumerate(roles) if role.node_label == piece.node_label
        ]
        if len(matches) != 2:
            return None
        distinct.append(
            DistinctRoleWiring(
                constraint_index=index,
                left_role_index=matches[0],
                right_role_index=matches[1],
            )
        )
    try:
        aggregate = _deterministic_aggregate_wiring(grouped)
    except SemanticCompileError:
        return None
    candidate = SemanticWiring(
        triples=triples,
        filters=filters,
        distinct_roles=distinct,
        aggregate=aggregate,
        rationale="Deterministic assembly because every selected label has one compatible role occurrence.",
    )
    return (
        candidate
        if not validate_wiring(
            candidate,
            grouped,
            relationship_free_mode=relationship_free_mode,
        )
        else None
    )


def _abstract_cyver(validators: tuple[Any, Any, Any], cypher: str) -> dict[str, Any]:
    raw = {}
    for name, validator in zip(
        ("syntax", "schema", "property"), validators, strict=True
    ):
        started = time.perf_counter()
        try:
            score, metadata = validator.validate(cypher)
            raw[name] = {
                "score": score,
                "metadata": _jsonable(metadata),
                "error": None,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        except Exception as error:
            raw[name] = {
                "score": None,
                "metadata": [],
                "error": {"type": type(error).__name__, "message": str(error)},
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
    normalized = json.loads(json.dumps(raw))
    syntax_meta = normalized["syntax"]["metadata"] or []
    ignored = [
        item
        for item in syntax_meta
        if item.get("code") == "Neo.ClientNotification.Statement.ParameterNotProvided"
    ]
    normalized["syntax"]["metadata"] = [
        item for item in syntax_meta if item not in ignored
    ]
    if raw["syntax"]["score"] is False and not normalized["syntax"]["metadata"]:
        normalized["syntax"]["score"] = True
    structural = [
        item
        for item in deterministic_errors(
            QueryPlan(cypher=cypher, parameters={}, explanation="abstract")
        )
        if not item.startswith(("missing parameter", "unused parameters"))
    ]
    errors = list(structural)
    if (
        not normalized["syntax"]["score"]
        or normalized["syntax"]["metadata"]
        or normalized["syntax"]["error"]
    ):
        errors.append("CyVer syntax validation failed")
    if (
        normalized["schema"]["score"] != 1
        or normalized["schema"]["metadata"]
        or normalized["schema"]["error"]
    ):
        errors.append("CyVer schema validation failed")
    if (
        normalized["property"]["score"] not in (None, 1, 1.0)
        or normalized["property"]["metadata"]
        or normalized["property"]["error"]
    ):
        errors.append("CyVer property validation failed")
    return {
        "raw_cyver": raw,
        "normalized_cyver": normalized,
        "ignored_expected_parameter_warnings": ignored,
        "errors": list(dict.fromkeys(errors)),
        "authorized_abstract_structure": not errors,
    }


def _binding_prompt(
    case: Case,
    contract: Any,
    feedback: dict[str, Any] | None,
    *,
    pattern: Any,
) -> str:
    items = []
    for index, item in enumerate(contract.slots):
        constraint = next(c for c in pattern.constraints if c.slot == item.name)
        value = {
            "index": index,
            "description": item.description,
            "value_type": item.value_type,
            "variable": constraint.variable,
            "node_label": item.node_label.value,
            "property": item.property.value,
            "operator": item.operator.value,
            "semantic_relationships": [
                relationship
                for relationship in pattern.relationships
                if constraint.variable
                in (relationship["source_variable"], relationship["target_variable"])
            ],
        }
        if item.allowed_values:
            value["allowed_values"] = item.allowed_values
        items.append(value)
    prompt = load_prompt("jev-staged/runner-binding-prompt-01", version=2).format(
        value_0=case.question
    ) + json.dumps({"slots": items, "relationships": pattern.relationships}, indent=2)
    if feedback:
        prompt += load_prompt(
            "jev-staged/runner-binding-prompt-02", version=1
        ) + json.dumps(feedback.get("failures", []), indent=2)
    return prompt


def _normalize_bill_name_bindings(
    contract: Any,
    raw: dict[str, Any],
    question: str,
) -> tuple[dict[str, Any], list[str]]:
    normalized = dict(raw)
    failures = []
    question_designation = parse_bill_designation(question)
    for slot in contract.slots:
        if (
            slot.node_label != NodeLabel.BILL
            or slot.property != PropertyName.NAME
            or slot.name not in raw
        ):
            continue
        designation = parse_bill_designation(raw[slot.name])
        if designation is not None:
            normalized[slot.name] = designation
            continue
        normalized.pop(slot.name)
        failure = (
            f"{slot.name} must be a Bill Designation in one of these forms: "
            "SB N, AB N, Senate Bill N, or Assembly Bill N; "
            f"received {raw[slot.name]!r}"
        )
        if question_designation is not None:
            failure += (
                f". The question contains {question_designation!r}; bind that "
                "Bill Designation rather than another phrase from the question"
            )
        failures.append(failure)
    return normalized, failures
