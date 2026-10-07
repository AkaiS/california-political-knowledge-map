import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from typing import Any

from neo4j import Query
from pydantic import BaseModel, ConfigDict, Field

from knowledge_map.jev.topology import (
    ConstraintOperator,
    NodeLabel,
    PatternPlan,
    PropertyName,
)


class BindingSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value_type: str
    required: bool = True
    cardinality: str = "exactly_one"
    node_label: NodeLabel
    property: PropertyName
    operator: ConstraintOperator
    allowed_values: list[str] | None = None
    resolution: str
    description: str


class BindingContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slots: list[BindingSlot]
    constraints: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Resolution:
    status: str
    value: str | None
    candidates: tuple[dict[str, str], ...]
    reason: str


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        try:
            return json.loads(value)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return value.decode(errors="replace")
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _match_labels(label: NodeLabel) -> str:
    if label == NodeLabel.PAC:
        return ":Organization:PAC"
    if label == NodeLabel.LABOR_UNION:
        return ":Organization:LaborUnion"
    return f":{label.value}"


def _domain_values(driver: Any, label: NodeLabel, prop: PropertyName) -> list[str]:
    query = (
        f"MATCH (n{_match_labels(label)}) WHERE n.{prop.value} IS NOT NULL "
        f"RETURN DISTINCT toString(n.{prop.value}) AS value ORDER BY value"
    )
    with driver.session(default_access_mode="READ") as session:
        return [record["value"] for record in session.run(Query(query, timeout=30.0))]


def build_binding_contract(driver: Any, pattern: PatternPlan) -> BindingContract:
    labels = {node.name: node.label for node in pattern.nodes}
    slots = []
    for constraint in pattern.constraints:
        label = labels[constraint.variable]
        allowed = None
        resolution = "canonical_entity"
        value_type = "string"
        if constraint.property == PropertyName.PUBLISHED_DATE:
            value_type = "date"
            resolution = "literal"
        elif constraint.property == PropertyName.SESSION or (
            label == NodeLabel.POLICY_AREA and constraint.property == PropertyName.NAME
        ):
            allowed = _domain_values(driver, label, constraint.property)
            value_type = "enum[string]"
            resolution = "domain_member"
        slots.append(
            BindingSlot(
                name=constraint.slot,
                value_type=value_type,
                node_label=label,
                property=constraint.property,
                operator=constraint.operator,
                allowed_values=allowed,
                resolution=resolution,
                description=constraint.description,
            )
        )
    cross_constraints = []
    starts = [s.name for s in slots if s.operator == ConstraintOperator.DATE_GTE]
    ends = [s.name for s in slots if s.operator == ConstraintOperator.DATE_LT]
    if starts and ends:
        cross_constraints.append(f"{starts[0]} < {ends[0]}")
    return BindingContract(slots=slots, constraints=cross_constraints)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _canonical_key(value: str, label: NodeLabel) -> str:
    normalized = _normalize_text(value)
    if label == NodeLabel.CAMPAIGN and normalized.endswith(" campaign"):
        normalized = normalized[: -len(" campaign")]
    return normalized


def _resolve_domain(value: str, allowed: list[str]) -> Resolution:
    exact = [item for item in allowed if item == value]
    folded = [item for item in allowed if item.casefold() == value.casefold()]
    normalized = [
        item for item in allowed if _normalize_text(item) == _normalize_text(value)
    ]
    matches = exact or folded or normalized
    if len(matches) == 1:
        return Resolution("selected", matches[0], (), "unique domain member")
    if len(matches) > 1:
        return Resolution("ambiguous", None, (), "multiple normalized domain members")
    return Resolution("no_match", None, (), "value is not in the declared domain")


def _entity_candidates(
    driver: Any,
    slot: BindingSlot,
    values: dict[str, Any],
    pattern: PatternPlan,
) -> list[dict[str, str]]:
    variable = next(c.variable for c in pattern.constraints if c.slot == slot.name)
    where = [f"n.{slot.property.value} IS NOT NULL"]
    parameters: dict[str, Any] = {}
    for constraint in pattern.constraints:
        if constraint.variable != variable or constraint.slot == slot.name:
            continue
        if constraint.property == PropertyName.SESSION and constraint.slot in values:
            where.append("n.session = $scope_session")
            parameters["scope_session"] = str(values[constraint.slot])
    query = (
        f"MATCH (n{_match_labels(slot.node_label)}) WHERE {' AND '.join(where)} "
        f"RETURN DISTINCT toString(n.id) AS id, toString(n.{slot.property.value}) AS value "
        "ORDER BY value, id"
    )
    with driver.session(default_access_mode="READ") as session:
        rows = [
            dict(record)
            for record in session.run(Query(query, timeout=30.0), parameters)
        ]
    by_id = {row["id"]: row for row in rows}
    return list(by_id.values())


def _resolve_entity(
    driver: Any,
    slot: BindingSlot,
    value: str,
    values: dict[str, Any],
    pattern: PatternPlan,
) -> Resolution:
    candidates = _entity_candidates(driver, slot, values, pattern)
    exact = [row for row in candidates if row["value"] == value]
    folded = [row for row in candidates if row["value"].casefold() == value.casefold()]
    canonical = [
        row
        for row in candidates
        if _canonical_key(row["value"], slot.node_label)
        == _canonical_key(value, slot.node_label)
    ]
    matches = exact or folded or canonical
    if len(matches) == 1:
        reason = "exact stored value" if exact else "unique canonical entity"
        return Resolution("selected", matches[0]["value"], tuple(matches), reason)
    if len(matches) > 1:
        return Resolution(
            "ambiguous", None, tuple(matches[:8]), "multiple project ids match"
        )
    nearby = [
        row
        for row in candidates
        if _normalize_text(value) in _normalize_text(row["value"])
        or _normalize_text(row["value"]) in _normalize_text(value)
    ][:8]
    return Resolution("no_match", None, tuple(nearby), "no canonical entity match")


def validate_and_resolve_bindings(
    driver: Any,
    contract: BindingContract,
    raw: dict[str, Any],
    pattern: PatternPlan,
) -> tuple[dict[str, str] | None, dict[str, Any]]:
    expected = {slot.name for slot in contract.slots}
    actual = set(raw)
    errors = []
    if missing := sorted(expected - actual):
        errors.append(f"missing required slots: {missing}")
    if extra := sorted(actual - expected):
        errors.append(f"extra slots: {extra}")
    normalized: dict[str, str] = {}
    resolutions: dict[str, Any] = {}
    # Resolve finite domains before entity lookup uses them as scope constraints.
    for slot in sorted(contract.slots, key=lambda slot: slot.allowed_values is None):
        if slot.name not in raw:
            continue
        value = raw[slot.name]
        if slot.value_type == "date":
            try:
                parsed = date.fromisoformat(str(value))
                normalized[slot.name] = parsed.isoformat()
                resolutions[slot.name] = {
                    "status": "selected",
                    "value": parsed.isoformat(),
                    "reason": "valid ISO date",
                    "candidates": [],
                }
            except ValueError:
                errors.append(f"{slot.name} must be an ISO date")
            continue
        if isinstance(value, (list, dict)) or value is None:
            errors.append(f"{slot.name} must contain exactly one scalar string")
            continue
        string_value = str(value).strip()
        if not string_value:
            errors.append(f"{slot.name} must not be empty")
            continue
        if slot.allowed_values is not None:
            resolution = _resolve_domain(string_value, slot.allowed_values)
        else:
            resolution = _resolve_entity(
                driver, slot, string_value, normalized, pattern
            )
        resolutions[slot.name] = _jsonable(resolution)
        if resolution.status == "selected" and resolution.value is not None:
            normalized[slot.name] = resolution.value
        else:
            errors.append(f"{slot.name}: {resolution.status}: {resolution.reason}")
    starts = [
        s.name for s in contract.slots if s.operator == ConstraintOperator.DATE_GTE
    ]
    ends = [s.name for s in contract.slots if s.operator == ConstraintOperator.DATE_LT]
    if (
        starts
        and ends
        and starts[0] in normalized
        and ends[0] in normalized
        and date.fromisoformat(normalized[starts[0]])
        >= date.fromisoformat(normalized[ends[0]])
    ):
        errors.append(f"declared constraint failed: {starts[0]} < {ends[0]}")
    return (
        normalized if not errors and set(normalized) == expected else None,
        {
            "valid": not errors and set(normalized) == expected,
            "expected_slots": sorted(expected),
            "actual_slots": sorted(actual),
            "normalized_bindings": normalized,
            "resolutions": resolutions,
            "failures": errors,
        },
    )
