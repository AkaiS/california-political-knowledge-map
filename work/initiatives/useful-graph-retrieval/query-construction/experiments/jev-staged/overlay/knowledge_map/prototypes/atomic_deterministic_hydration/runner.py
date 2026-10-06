"""PROTOTYPE: atomic semantic composition with deterministic hydration."""

# A batch experiment records individual failures instead of aborting.
# ruff: noqa: BLE001

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import logfire
from CyVer.validators.properties_validator import PropertiesValidator
from CyVer.validators.schema_validator import SchemaValidator
from CyVer.validators.syntax_validator import SyntaxValidator
from dotenv import load_dotenv
from neo4j import GraphDatabase
from pydantic_ai import Agent
from typesafe_sdk import TypeSafeClient

from knowledge_map.core.bill_sessions import parse_bill_designation
from knowledge_map.ontology import news
from knowledge_map.prototypes.atomic_deterministic_hydration.catalog import (
    BY_ID,
    CATALOG,
    COMPILER_NEWS_ARTICLE_ROLE,
    SEMANTIC_LABELS,
    SEMANTIC_PREDICATES,
    Piece,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.compiler import (
    CompiledSemantic,
    SemanticCompileError,
    compile_semantic,
    validate_wiring,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.contracts import (
    AggregateWiring,
    ComposerWiring,
    DistinctRoleWiring,
    FilterWiring,
    PieceSelection,
    PositionalBindings,
    SemanticSchemaSelection,
    SemanticWiring,
    TripleWiring,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.jev_filtered_selector import (
    select_pieces as select_pieces_with_filtered_jev,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.jev_schema_filter import (
    DEFAULT_THRESHOLD as DEFAULT_SCHEMA_THRESHOLD,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.jev_schema_filter import (
    narrow_schema,
    validate_threshold,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.jev_selector import (
    select_pieces as select_pieces_with_jev,
)
from knowledge_map.prototypes.atomic_deterministic_hydration.jev_staged_selector import (
    select_pieces as select_pieces_with_staged_jev,
)
from knowledge_map.prototypes.composable_triples.compiler import NODE_PROPERTIES
from knowledge_map.prototypes.composable_triples.contracts import (
    ConstraintOperator,
    NodeLabel,
    Predicate,
    PropertyName,
)
from knowledge_map.prototypes.cyver_extended.runner import (
    Case,
    QueryPlan,
    _agent_call,
    _execute,
    _file_sha,
    _load_references,
    deterministic_errors,
    validate_plan,
)
from knowledge_map.prototypes.pattern_bound_cyver.runner import (
    _jsonable,
    build_binding_contract,
    overlap_score,
    validate_and_resolve_bindings,
)
from knowledge_map.utils.agents import create_agent
from knowledge_map.utils.deployments import deployment_from_environment
from knowledge_map.utils.models import DEFAULT_LOCAL_CHAT_MODEL, get_chat_model

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
QUESTIONS = ROOT / "src/knowledge_map/prototypes/atomic_composer_cyver/questions.json"
REFERENCES = (
    ROOT
    / "work/initiatives/useful-graph-retrieval/query-construction/verified-results.json"
)
DEFAULT_OUTPUT = HERE / "results/full-report.json"
DEFAULT_EVENTS = HERE / "results/raw-stage-events.jsonl"

FILTER_INSTRUCTIONS = """Select semantic labels, semantic relationships, and properties needed to anchor or filter the question. Article source and result roles are compiler-owned; select only their relationship or filter semantics. Do not choose output fields, result shape, storage mechanics, query syntax, parameter names, or values. Use only names in the supplied semantic schema."""

SELECTOR_INSTRUCTIONS = """Choose compiler-assigned IDs for the semantic entity-role occurrences, semantic triple occurrences, question-derived filters, distinct-entity constraints, and genuine aggregate operations needed by the question. Return IDs only in the typed groups. Repeat a role or relationship ID when the question needs two occurrences. Article relationship, filter, and aggregate IDs add their article role in code; there is no article role ID to select. Reporting context is automatic and must not be represented in the selection. Do not choose output fields, result shape, joins, directions, parameter names, values, query syntax, or an answer."""

COMPOSER_INSTRUCTIONS = """Wire exactly the selected semantic occurrences using their zero-based indexes. Relationship indexes refer to the selected relationship list, role indexes to the selected role list, filter indexes to the selected filter list, and constraint indexes to the selected distinct-role list. Use each selected relationship, filter, and constraint exactly once. The selected piece declares each relationship's source and target labels. Do not emit names for roles, claims, parameters, outputs, or query syntax. Reporting context and result shape are automatic."""

BINDER_INSTRUCTIONS = """Return the concrete question values in the exact supplied order. Return only the values list. Do not name fields or parameters, change semantic structure, choose output fields, or write query syntax. Dates are ISO YYYY-MM-DD boundaries. Use an allowed value when the item supplies a closed set."""

FORBIDDEN_MODEL_TERMS = (
    "Chunk",
    "MENTIONED_IN",
    "HAS_CHUNK",
    "r.chunks",
    "r.articles",
    "evidence_groups",
    "claim_name",
    "return_targets",
    "slot",
    "variable",
    "alias",
)


def _load_questions() -> list[Case]:
    return [Case(**item) for item in json.loads(QUESTIONS.read_text())]


def _build_agents(deployment_kind: str, model_override: str | None):
    os.environ.setdefault(
        "PYTEST_CURRENT_TEST", "atomic-deterministic-hydration-local-only"
    )
    deployment = deployment_from_environment(
        deployment_kind,
        default_local_model=DEFAULT_LOCAL_CHAT_MODEL,
        model_override=model_override,
        command_name="Atomic deterministic hydration prototype",
    )
    deployment = deployment.model_copy(
        update={
            "request_settings": deployment.request_settings.model_copy(
                update={"timeout": 120.0, "max_tokens": 3000, "max_attempts": 2}
            )
        }
    )
    model = get_chat_model(deployment)
    return (
        deployment,
        model,
        create_agent(
            model,
            name="semantic_schema_filter_agent",
            output_type=SemanticSchemaSelection,
            instructions=FILTER_INSTRUCTIONS,
            retries=2,
        ),
        create_agent(
            model,
            name="semantic_piece_selector_agent",
            output_type=PieceSelection,
            instructions=SELECTOR_INSTRUCTIONS,
            retries=2,
        ),
        create_agent(
            model,
            name="semantic_wiring_composer_agent",
            output_type=ComposerWiring,
            instructions=COMPOSER_INSTRUCTIONS,
            retries=2,
        ),
    )


def semantic_schema() -> str:
    lines = ["SEMANTIC ENTITY LABELS"]
    for label in SEMANTIC_LABELS:
        allowed = {
            PropertyName.NAME,
            PropertyName.SESSION,
            PropertyName.TITLE,
            PropertyName.PUBLISHED_DATE,
        }
        properties = sorted(prop.value for prop in NODE_PROPERTIES[label] & allowed)
        lines.append(f"- {label.value}: filterable={','.join(properties)}")
    lines.append("- Article (compiler-owned): filterable=published_date,title")
    lines.append("SEMANTIC RELATIONSHIPS")
    for predicate in SEMANTIC_PREDICATES:
        shape = news.RELATIONSHIPS[predicate.value]
        sources = [
            "Article" if label == "NewsArticle" else label
            for label in sorted(shape.source_labels)
        ]
        targets = [
            "Article" if label == "NewsArticle" else label
            for label in sorted(shape.target_labels)
        ]
        lines.append(
            f"- ({'|'.join(sources)})-[:{predicate.value}]->({'|'.join(targets)})"
        )
    return "\n".join(lines) + "\n"


def _filter_prompt(case: Case) -> str:
    return f"Question: {case.question}\n\n{semantic_schema()}"


def _catalog_prompt() -> str:
    groups: dict[str, list[str]] = {}
    for piece in CATALOG:
        groups.setdefault(piece.kind, []).append(
            f"{piece.piece_id}: {piece.description}"
        )
    return "\n".join(
        f"{kind.upper()} PIECES\n" + "\n".join(items) for kind, items in groups.items()
    )


def _selector_prompt(
    case: Case,
    schema_selection: SemanticSchemaSelection,
    feedback: dict[str, Any] | None,
) -> str:
    prompt = (
        f"Question: {case.question}\n\nSemantic schema selection:\n"
        + schema_selection.model_dump_json(indent=2)
        + "\n\nSemantic piece catalog:\n"
        + _catalog_prompt()
    )
    if feedback:
        prompt += "\n\nCorrect the prior ID selection:\n" + json.dumps(
            feedback, indent=2
        )
    return prompt


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
    prompt = (
        f"Question: {case.question}\n\nSelected semantic occurrences, indexed within each list:\n"
        + json.dumps(safe, indent=2)
    )
    if filter_attachment_rules:
        prompt += (
            "\n\nFilter attachment rules derived after fragment selection:\n"
            + json.dumps(filter_attachment_rules, indent=2)
        )
    if previous is not None:
        prompt += (
            "\n\nPrior wiring:\n"
            + previous.model_dump_json(indent=2)
            + "\n\nCorrect these semantic wiring errors:\n"
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


def _relationship_free_mode(question: str) -> str:
    """Admit co-occurrence only when the question explicitly asks for it."""

    words = set(re.findall(r"[a-z]+", question.lower()))
    asks_for_reporting_lookup = "reporting" in words and bool(
        words & {"mention", "mentions", "mentioned", "attach", "attached"}
    )
    asks_for_shared_chunks = (
        {"same", "reporting"} <= words
        and any(word.startswith("appear") for word in words)
        and any(word.startswith("chunk") for word in words)
    )
    if asks_for_reporting_lookup or asks_for_shared_chunks:
        return "shared_reporting"
    return "forbidden"


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
) -> str:
    items = []
    for index, item in enumerate(contract.slots):
        value = {
            "index": index,
            "description": item.description,
            "value_type": item.value_type,
        }
        if item.allowed_values:
            value["allowed_values"] = item.allowed_values
        items.append(value)
    prompt = f"Question: {case.question}\n\nRequired values in order:\n" + json.dumps(
        items, indent=2
    )
    if feedback:
        prompt += (
            "\n\nThe prior ordered values failed validation. Return a corrected "
            "complete list. Fix these errors:\n"
            + json.dumps(feedback.get("failures", []), indent=2)
        )
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


def _bind_positional(
    model: Any,
    driver: Any,
    case: Case,
    compiled: CompiledSemantic,
    retries: int,
) -> dict[str, Any]:
    contract = build_binding_contract(driver, compiled.binding_pattern)
    agent = create_agent(
        model,
        name="semantic_positional_value_agent",
        output_type=PositionalBindings,
        instructions=BINDER_INSTRUCTIONS,
        retries=2,
    )
    attempts = []
    feedback = None
    validated = None
    for number in range(1, retries + 2):
        prompt = _binding_prompt(case, contract, feedback)
        call = _agent_call(agent, prompt)
        validation = None
        if call["ok"]:
            values = PositionalBindings.model_validate(call["output"]).values
            if len(values) == len(contract.slots):
                raw = {
                    item.name: value
                    for item, value in zip(contract.slots, values, strict=True)
                }
                normalized_raw, bill_failures = _normalize_bill_name_bindings(
                    contract, raw, case.question
                )
                if bill_failures:
                    validation = {
                        "valid": False,
                        "normalized_bindings": normalized_raw,
                        "failures": bill_failures,
                    }
                else:
                    validated, validation = validate_and_resolve_bindings(
                        driver,
                        contract,
                        normalized_raw,
                        compiled.binding_pattern,
                    )
            else:
                validation = {
                    "valid": False,
                    "failures": [
                        (
                            f"expected {len(contract.slots)} ordered values, "
                            f"received {len(values)}"
                        )
                    ],
                }
            feedback = validation
        else:
            feedback = {"failures": [call["error"]]}
        attempts.append(
            {
                "number": number,
                "prompt": prompt,
                "call": call,
                "raw_output": call.get("output"),
                "validation": validation,
            }
        )
        if validated is not None:
            break
    return {
        "model_facing_ordered_contract": [
            {
                "index": index,
                "description": item.description,
                "value_type": item.value_type,
                "allowed_values": item.allowed_values,
            }
            for index, item in enumerate(contract.slots)
        ],
        "attempts": attempts,
        "normalized_resolved_bindings": validated,
        "valid": validated is not None,
    }


def _usage(calls: list[dict[str, Any]]) -> dict[str, int | float]:
    result: dict[str, int | float] = {
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "latency_ms": 0.0,
    }
    for call in calls:
        raw = call.get("usage", {}) if call else {}
        for key in ("requests", "input_tokens", "output_tokens", "total_tokens"):
            result[key] += int(raw.get(key) or 0)
        result["latency_ms"] += float(call.get("latency_ms") or 0)
    result["latency_ms"] = round(float(result["latency_ms"]), 1)
    return result


def _finish(record: dict[str, Any], started: float) -> dict[str, Any]:
    composer_calls = [
        item["call"]
        for item in record["composition_stage"]["attempts"]
        if item.get("call")
    ]
    binder_calls = [
        item["call"] for item in (record.get("binding_stage") or {}).get("attempts", [])
    ]
    record["model_usage_by_stage"] = {
        "schema_filter": _usage([record["schema_filter_stage"]["call"]]),
        "selector": _usage(
            [item["call"] for item in record["selection_stage"]["attempts"]]
        ),
        "composer": _usage(composer_calls),
        "binder": _usage(binder_calls),
    }
    record["total_latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return record


def _payload(rows: list[dict[str, Any]]) -> dict[str, int]:
    def fields(value: Any) -> int:
        if isinstance(value, dict):
            return len(value) + sum(fields(item) for item in value.values())
        if isinstance(value, list):
            return sum(fields(item) for item in value)
        return 0

    serialized = json.dumps(_jsonable(rows), ensure_ascii=False, separators=(",", ":"))
    return {
        "bytes": len(serialized.encode()),
        "field_count": fields(rows),
        "row_count": len(rows),
        "embedding_fields": serialized.count('"embedding"'),
    }


def run_case(
    case: Case,
    model: Any,
    filter_agent: Agent,
    selector_agent: Agent | None,
    composer_agent: Agent,
    driver: Any,
    validators: tuple[Any, Any, Any],
    *,
    jev_client: TypeSafeClient | None,
    selector_backend: str,
    timeout: float,
    schema_filter_backend: str = "pydantic",
    schema_threshold: float = DEFAULT_SCHEMA_THRESHOLD,
) -> dict[str, Any]:
    started = time.perf_counter()
    if schema_filter_backend == "jev":
        if jev_client is None:
            raise ValueError("Jev schema filtering requires a TypeSafe client")
        filter_call = narrow_schema(
            jev_client, case.question, threshold=schema_threshold
        )
        filter_prompt = filter_call["model_visible_prompt"]
    else:
        filter_prompt = _filter_prompt(case)
        filter_call = _agent_call(filter_agent, filter_prompt)
    schema_selection = (
        SemanticSchemaSelection.model_validate(filter_call["output"])
        if filter_call["ok"]
        else SemanticSchemaSelection(
            labels=[], relationships=[], rationale="call failed"
        )
    )
    schema_stage = {
        "backend": schema_filter_backend,
        "prompt": filter_prompt,
        "call": filter_call,
        "output": schema_selection.model_dump(mode="json"),
    }
    selector_attempts = []
    grouped = {
        kind: []
        for kind in ("role", "relationship", "filter", "role_constraint", "aggregation")
    }
    feedback = None
    filter_attachment_rules: list[dict[str, str]] = []
    schema_failed = schema_filter_backend == "jev" and not filter_call["ok"]
    selector_attempt_count = (
        0
        if schema_failed
        else 1
        if selector_backend in {"jev", "jev-filtered", "jev-staged"}
        else 3
    )
    if schema_failed:
        selector_attempts.append(
            {
                "number": 0,
                "prompt": "",
                "selection": None,
                "call": {"usage": {}, "latency_ms": 0.0},
                "errors": ["selector skipped after Jev schema-filter failure"],
            }
        )
    for number in range(1, selector_attempt_count + 1):
        if selector_backend in {"jev", "jev-filtered", "jev-staged"}:
            selector = (
                select_pieces_with_staged_jev
                if selector_backend == "jev-staged"
                else select_pieces_with_filtered_jev
                if selector_backend == "jev-filtered"
                else select_pieces_with_jev
            )
            call = selector(jev_client, case.question, schema_selection)
            prompt = call["model_visible_prompt"]
            filter_attachment_rules = call.get("filter_attachment_rules", [])
        else:
            prompt = _selector_prompt(case, schema_selection, feedback)
            call = _agent_call(selector_agent, prompt)
        selection = None
        errors = list(call.get("normalization_errors", []))
        if call["ok"]:
            selection = PieceSelection.model_validate(call["output"])
            grouped, resolution_errors = _resolve_selection(
                selection, allow_parent_roles=selector_backend == "jev-staged"
            )
            if selector_backend == "jev-staged":
                grouped["role_constraint"] = [
                    BY_ID[pid] for pid in selection.role_constraint_ids
                ]
            errors.extend(resolution_errors)
        else:
            errors.append("model call failed")
        selector_attempts.append(
            {
                "number": number,
                "prompt": prompt,
                "call": call,
                "selection": selection.model_dump(mode="json") if selection else None,
                "errors": errors,
            }
        )
        if not errors:
            break
        feedback = {
            "errors": errors,
            "instruction": "Return the full corrected selection.",
        }
    record = {
        "opaque_id": case.opaque_id,
        "case_id": case.source_id,
        "question": case.question,
        "schema_filter_stage": schema_stage,
        "selection_stage": {
            "attempts": selector_attempts,
            "resolved_pieces": {
                kind: [piece.public() for piece in pieces]
                for kind, pieces in grouped.items()
            },
            "selected_piece_count": sum(map(len, grouped.values())),
        },
        "composition_stage": {"attempts": [], "composer_call_count": 0},
        "binding_stage": None,
        "validation_stage": None,
        "execution": {
            "ok": False,
            "rows": [],
            "error": "not reached",
            "latency_ms": 0.0,
        },
        "failure_stage": None,
    }
    if selector_attempts[-1]["errors"]:
        record["failure_stage"] = (
            "schema_filter"
            if schema_failed
            else "selector_abstention"
            if selector_attempts[-1]["call"].get("abstention")
            else "selector"
        )
        return _finish(record, started)

    relationship_free_mode = _relationship_free_mode(case.question)
    compiled = None
    prior: ComposerWiring | None = None
    composition_feedback = None
    compiler_owns_article_role = any(
        piece.piece_id == COMPILER_NEWS_ARTICLE_ROLE.piece_id
        for piece in grouped["role"]
    )
    if compiler_owns_article_role:
        deterministic = _deterministic_unique_wiring(
            grouped, relationship_free_mode=relationship_free_mode
        )
        if deterministic is not None:
            candidate = compile_semantic(
                deterministic,
                grouped,
                relationship_free_mode=relationship_free_mode,
                allow_parent_distinct=selector_backend == "jev-staged",
            )
            cyver = _abstract_cyver(validators, candidate.cypher)
            record["composition_stage"]["attempts"].append(
                {
                    "number": 1,
                    "prompt": None,
                    "call": None,
                    "kind": "compiler_owned_article_wiring",
                    "wiring": deterministic.model_dump(mode="json"),
                    "errors": cyver["errors"],
                    "parameterized_cypher": candidate.cypher,
                    "cyver": cyver,
                }
            )
            if cyver["authorized_abstract_structure"]:
                compiled = candidate
    for number in range(1, 4):
        if compiler_owns_article_role:
            break
        prompt = _composer_prompt(
            case,
            grouped,
            filter_attachment_rules,
            prior,
            composition_feedback,
        )
        call = _agent_call(composer_agent, prompt)
        attempt = {
            "number": number,
            "prompt": prompt,
            "call": call,
            "wiring": call.get("output"),
            "errors": [],
            "parameterized_cypher": None,
            "cyver": None,
        }
        record["composition_stage"]["composer_call_count"] += 1
        if call["ok"]:
            prior = ComposerWiring.model_validate(call["output"])
            try:
                semantic_wiring = _semantic_wiring_from_composer(prior, grouped)
                errors = validate_wiring(
                    semantic_wiring,
                    grouped,
                    relationship_free_mode=relationship_free_mode,
                    allow_parent_distinct=selector_backend == "jev-staged",
                )
                if selector_backend == "jev-staged" and filter_attachment_rules:
                    required = filter_attachment_rules[0]
                    actual = prior.model_dump(mode="json")
                    for field in ("triples", "filters", "distinct_roles"):
                        canonical = lambda items: sorted(
                            json.dumps(item, sort_keys=True) for item in items
                        )
                        if canonical(actual[field]) != canonical(required[field]):
                            errors.append(
                                f"composer must preserve staged {field} occurrence attachments"
                            )
            except SemanticCompileError as error:
                semantic_wiring = None
                errors = [str(error)]
            attempt["errors"] = errors
            if not errors:
                try:
                    candidate = compile_semantic(
                        semantic_wiring,
                        grouped,
                        relationship_free_mode=relationship_free_mode,
                        allow_parent_distinct=selector_backend == "jev-staged",
                    )
                    cyver = _abstract_cyver(validators, candidate.cypher)
                    attempt["parameterized_cypher"] = candidate.cypher
                    attempt["cyver"] = cyver
                    if cyver["authorized_abstract_structure"]:
                        compiled = candidate
                    else:
                        errors = cyver["errors"]
                except SemanticCompileError as error:
                    errors = [str(error)]
                attempt["errors"] = errors
            composition_feedback = {"errors": errors}
        else:
            composition_feedback = {"errors": ["model call failed"]}
        record["composition_stage"]["attempts"].append(attempt)
        if compiled:
            break
    if not compiled:
        deterministic = _deterministic_unique_wiring(
            grouped, relationship_free_mode=relationship_free_mode
        )
        if deterministic is not None:
            candidate = compile_semantic(
                deterministic,
                grouped,
                relationship_free_mode=relationship_free_mode,
                allow_parent_distinct=selector_backend == "jev-staged",
            )
            cyver = _abstract_cyver(validators, candidate.cypher)
            record["composition_stage"]["attempts"].append(
                {
                    "number": len(record["composition_stage"]["attempts"]) + 1,
                    "prompt": None,
                    "call": None,
                    "kind": "deterministic_unique_fallback",
                    "wiring": deterministic.model_dump(mode="json"),
                    "errors": cyver["errors"],
                    "parameterized_cypher": candidate.cypher,
                    "cyver": cyver,
                }
            )
            if cyver["authorized_abstract_structure"]:
                compiled = candidate
    if not compiled:
        record["failure_stage"] = "composer_or_prebinding_validation"
        return _finish(record, started)

    record["composition_stage"].update(
        {
            "final_semantic_wiring": compiled.wiring.model_dump(mode="json"),
            "compiler_generated_parameterized_cypher": compiled.cypher,
            "compiler_generated_parameter_names": list(compiled.slots),
            "deterministic_evidence_rules": _jsonable(compiled.evidence_rules),
        }
    )
    binding = _bind_positional(model, driver, case, compiled, retries=2)
    record["binding_stage"] = binding
    if not binding["valid"]:
        record["failure_stage"] = "binder_or_binding_contract"
        return _finish(record, started)
    parameters = binding["normalized_resolved_bindings"]
    plan = QueryPlan(
        cypher=compiled.cypher,
        parameters=parameters,
        explanation="compiler-generated query with deterministic output and context hydration",
    )
    validation = validate_plan(driver, validators, plan, timeout)
    record["validation_stage"] = validation
    if not validation["authorized"]:
        record["failure_stage"] = "post_binding_validation"
        return _finish(record, started)
    record["execution"] = _execute(driver, plan, timeout)
    record["execution"]["payload"] = _payload(record["execution"]["rows"])
    if not record["execution"]["ok"]:
        record["failure_stage"] = "execution"
    elif not record["execution"]["rows"]:
        record["failure_stage"] = "empty_result"
    return _finish(record, started)


def _score(records: list[dict[str, Any]]) -> None:
    references = _load_references(REFERENCES)
    for record in records:
        reference = references[record["case_id"]]
        record["returned_subgraph"] = overlap_score(
            record["execution"]["rows"], reference
        )
        metric = record["returned_subgraph"]["combined_nodes_and_evidence"]
        record["retrieval_classification"] = (
            "exact"
            if not metric["missing"] and not metric["extra"]
            else "under_return"
            if metric["missing"]
            else "over_broad"
        )
        record["expected_rows"] = reference.get("rows", reference.get("result", []))
        if (
            record["failure_stage"] is None
            and record["retrieval_classification"] != "exact"
        ):
            record["failure_stage"] = "semantic_retrieval"


def _expected_selection(source_id: str) -> dict[str, list[str]]:
    """Load the semantic oracle only after execution and map it to compiler pieces."""

    from knowledge_map.prototypes.composable_triples.oracles import ORACLE_PATTERNS

    plan = ORACLE_PATTERNS[source_id]
    variables = {node.name: node.label for node in plan.nodes}

    def relationship_id(subject: str, predicates: list[Predicate], object_: str) -> str:
        source = variables[subject]
        target = variables[object_]
        for piece in CATALOG:
            if (
                piece.kind == "relationship"
                and piece.source_label == source
                and piece.target_label == target
                and piece.predicates == tuple(predicates)
            ):
                return piece.piece_id
        raise KeyError((source, predicates, target))

    def label_id(label: NodeLabel) -> str:
        return "ARTICLE" if label == NodeLabel.NEWS_ARTICLE else label.value.upper()

    return {
        "role_ids": [
            f"ROLE__{node.label.value.upper()}"
            for node in plan.nodes
            if node.label not in {NodeLabel.CHUNK, NodeLabel.NEWS_ARTICLE}
        ],
        "relationship_ids": [
            relationship_id(triple.subject, triple.predicates, triple.object)
            for triple in plan.triples
            if not set(triple.predicates)
            & {Predicate.MENTIONED_IN, Predicate.HAS_CHUNK}
        ],
        "filter_ids": [
            f"FILTER__{label_id(variables[item.variable])}__{item.property.value.upper()}__{item.operator.value.upper()}"
            for item in plan.constraints
        ],
        "role_constraint_ids": [
            f"DISTINCT__{variables[item.left_variable].value.upper()}__ROLES"
            for item in plan.inequalities
        ],
        "aggregation_ids": ["AGG__POLICYAREA__COUNT_ARTICLE"] if plan.aggregate else [],
    }


def _score_selections(records: list[dict[str, Any]]) -> None:
    """Score selector output after execution so semantic oracles never affect a query."""

    fields = (
        "role_ids",
        "relationship_ids",
        "filter_ids",
        "role_constraint_ids",
        "aggregation_ids",
    )
    for record in records:
        actual = record["selection_stage"]["attempts"][-1].get("selection") or {
            field: [] for field in fields
        }
        expected = _expected_selection(record["case_id"])
        actual_counts = Counter(
            piece_id for field in fields for piece_id in actual[field]
        )
        expected_counts = Counter(
            piece_id for field in fields for piece_id in expected[field]
        )
        overlap = sum((actual_counts & expected_counts).values())
        selected = sum(actual_counts.values())
        required = sum(expected_counts.values())
        precision = overlap / selected if selected else (1.0 if not required else 0.0)
        recall = overlap / required if required else 1.0
        record["semantic_selection"] = {
            "exact": actual_counts == expected_counts,
            "selected_occurrences": selected,
            "required_occurrences": required,
            "overlap_occurrences": overlap,
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0,
            "missing": dict(expected_counts - actual_counts),
            "extra": dict(actual_counts - expected_counts),
        }


def _metric(records: list[dict[str, Any]], name: str) -> dict[str, Any]:
    metrics = [record["returned_subgraph"][name] for record in records]
    expected = sum(item["expected"] for item in metrics)
    returned = sum(item["returned"] for item in metrics)
    overlap = sum(item["overlap"] for item in metrics)
    recall = overlap / expected if expected else 1.0
    precision = overlap / returned if returned else (1.0 if not expected else 0.0)
    return {
        "expected": expected,
        "returned": returned,
        "overlap": overlap,
        "recall": recall,
        "precision": precision,
        "f1": 2 * recall * precision / (recall + precision)
        if recall + precision
        else 0.0,
        "jaccard": overlap / (expected + returned - overlap)
        if expected + returned - overlap
        else 1.0,
        "macro_recall": statistics.fmean(item["recall"] for item in metrics),
        "macro_precision": statistics.fmean(item["precision"] for item in metrics),
        "macro_f1": statistics.fmean(item["f1"] for item in metrics),
        "macro_jaccard": statistics.fmean(item["jaccard"] for item in metrics),
        "exact_set_matches": sum(
            not item["missing"] and not item["extra"] for item in metrics
        ),
    }


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"min": 0.0, "p50": 0.0, "p90": 0.0, "max": 0.0}
    return {
        "min": round(ordered[0], 1),
        "p50": round(statistics.median(ordered), 1),
        "p90": round(ordered[max(0, int(len(ordered) * 0.9) - 1)], 1),
        "max": round(ordered[-1], 1),
    }


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    payloads = [record["execution"].get("payload", {}) for record in records]
    selection_overlap = sum(
        record["semantic_selection"]["overlap_occurrences"] for record in records
    )
    selection_selected = sum(
        record["semantic_selection"]["selected_occurrences"] for record in records
    )
    selection_required = sum(
        record["semantic_selection"]["required_occurrences"] for record in records
    )
    selection_precision = (
        selection_overlap / selection_selected if selection_selected else 0.0
    )
    selection_recall = (
        selection_overlap / selection_required if selection_required else 1.0
    )
    return {
        "case_count": len(records),
        "executed": sum(record["execution"]["ok"] for record in records),
        "nonempty": sum(bool(record["execution"]["rows"]) for record in records),
        "stopped": sum(not record["execution"]["ok"] for record in records),
        "retrieval_classifications": dict(
            Counter(record["retrieval_classification"] for record in records)
        ),
        "failures_by_stage": dict(
            Counter(record["failure_stage"] or "none" for record in records)
        ),
        "semantic_selection": {
            "exact": sum(record["semantic_selection"]["exact"] for record in records),
            "selected_occurrences": selection_selected,
            "required_occurrences": selection_required,
            "overlap_occurrences": selection_overlap,
            "precision": selection_precision,
            "recall": selection_recall,
            "f1": 2
            * selection_precision
            * selection_recall
            / (selection_precision + selection_recall)
            if selection_precision + selection_recall
            else 0.0,
        },
        "case_runtime_ms": _distribution(
            [record["total_latency_ms"] for record in records]
        ),
        "payload": {
            "bytes": sum(item.get("bytes", 0) for item in payloads),
            "field_count": sum(item.get("field_count", 0) for item in payloads),
            "embedding_fields": sum(
                item.get("embedding_fields", 0) for item in payloads
            ),
        },
        "returned_subgraph_overlap": {
            name: _metric(records, name)
            for name in (
                "nodes",
                "evidence_chunks",
                "combined_nodes_and_evidence",
                "explicit_relationship_values",
            )
        },
    }


def _aggregate_usage(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, int | float]]:
    return {
        stage: {
            key: sum(record["model_usage_by_stage"][stage][key] for record in records)
            for key in (
                "requests",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "latency_ms",
            )
        }
        for stage in ("schema_filter", "selector", "composer", "binder")
    }


def _append_event(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(_jsonable(record), ensure_ascii=False) + "\n")


def _jev_telemetry(records: list[dict[str, Any]]) -> dict[str, Any]:
    cases = []
    for record in records:
        call = record["selection_stage"]["attempts"][-1]["call"]
        decisions = call.get("decisions", {}) if call else {}
        near = [
            {
                "fragment_id": fragment_id,
                "score": decision["score"],
                "distance_from_threshold": round(abs(decision["score"] - 0.52), 4),
                "selected": decision["score"] >= 0.52,
            }
            for fragment_id, decision in decisions.items()
            if abs(decision["score"] - 0.52) <= 0.05
        ]
        cases.append(
            {
                "opaque_id": record["opaque_id"],
                "candidate_count": (call.get("pruning") or {}).get("candidate_count"),
                "model": call.get("model"),
                "requests": (call.get("usage") or {}).get("requests", 0),
                "input_tokens": (call.get("usage") or {}).get("input_tokens", 0),
                "output_tokens": (call.get("usage") or {}).get("output_tokens", 0),
                "total_tokens": (call.get("usage") or {}).get("total_tokens", 0),
                "latency_ms": call.get("latency_ms", 0.0),
                "retry_count": call.get("retry_count"),
                "near_threshold_decisions": near,
            }
        )
    counts = [item["candidate_count"] for item in cases if item["candidate_count"]]
    latencies = [item["latency_ms"] for item in cases]
    return {
        "threshold": 0.52,
        "retry_count_available": any(item["retry_count"] is not None for item in cases),
        "models": sorted({item["model"] for item in cases if item["model"]}),
        "candidate_count": {
            "total": sum(counts),
            "median": statistics.median(counts) if counts else 0,
            "range": [min(counts), max(counts)] if counts else [0, 0],
        },
        "requests": sum(item["requests"] for item in cases),
        "input_tokens": sum(item["input_tokens"] for item in cases),
        "output_tokens": sum(item["output_tokens"] for item in cases),
        "total_tokens": sum(item["total_tokens"] for item in cases),
        "summed_latency_ms": round(sum(latencies), 1),
        "median_latency_ms": round(statistics.median(latencies), 1)
        if latencies
        else 0.0,
        "latency_range_ms": [min(latencies), max(latencies)]
        if latencies
        else [0.0, 0.0],
        "near_threshold_decisions": [
            {"opaque_id": item["opaque_id"], **decision}
            for item in cases
            for decision in item["near_threshold_decisions"]
        ],
        "cases": cases,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    load_dotenv()
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_USERNAME", os.environ.get("NEO4J_USER", "neo4j")),
            os.environ["NEO4J_PASSWORD"],
        ),
    )
    driver.verify_connectivity()
    validators = (
        SyntaxValidator(driver),
        SchemaValidator(driver),
        PropertiesValidator(driver),
    )
    cases = [
        case
        for case in _load_questions()
        if not args.case or case.source_id in args.case or case.opaque_id in args.case
    ]
    if args.output.exists() or args.raw_events.exists():
        raise FileExistsError("refusing to overwrite a prior experiment artifact")
    deployment, model, filter_agent, selector_agent, composer_agent = _build_agents(
        args.deployment, args.model
    )
    jev_client = (
        TypeSafeClient()
        if args.selector in {"jev", "jev-filtered", "jev-staged"}
        or args.schema_filter == "jev"
        else None
    )
    if args.selector in {"jev", "jev-filtered", "jev-staged"}:
        selector_agent = None
    records = []
    started = time.perf_counter()
    try:
        with logfire.span(
            "atomic_deterministic_hydration.workflow", case_count=len(cases)
        ):
            for case in cases:
                print(
                    f"[{case.opaque_id}/{case.source_id}] {case.question}", flush=True
                )
                record = run_case(
                    case,
                    model,
                    filter_agent,
                    selector_agent,
                    composer_agent,
                    driver,
                    validators,
                    jev_client=jev_client,
                    selector_backend=args.selector,
                    timeout=args.query_timeout,
                    schema_filter_backend=args.schema_filter,
                    schema_threshold=args.schema_threshold,
                )
                records.append(record)
                _append_event(args.raw_events, record)
    finally:
        driver.close()
    _score(records)
    _score_selections(records)
    usage = _aggregate_usage(records)
    model_visible_prompts = [
        item
        for record in records
        for item in (
            [record["schema_filter_stage"]["prompt"]]
            + [attempt["prompt"] for attempt in record["selection_stage"]["attempts"]]
            + [
                attempt["prompt"]
                for attempt in record["composition_stage"]["attempts"]
                if attempt.get("prompt")
            ]
            + [
                attempt["prompt"]
                for attempt in (record.get("binding_stage") or {}).get("attempts", [])
            ]
        )
    ]
    report = {
        "prototype": "atomic-semantic-composer-deterministic-provenance-and-output-hydration",
        "selector_backend": args.selector,
        "schema_filter_backend": args.schema_filter,
        "schema_filter_policy": {
            "threshold": args.schema_threshold if args.schema_filter == "jev" else None,
            "threshold_status": "experimental, uncalibrated"
            if args.schema_filter == "jev"
            else None,
            "endpoint_closure": "all valid catalog endpoint alternatives"
            if args.schema_filter == "jev"
            else "unchanged local schema output",
            "downstream_property_pruning": "unchanged: all filter properties of retained labels are available",
        },
        "created_at": datetime.now().astimezone().isoformat(),
        "run_kind": "complete-25-case-batch" if len(records) == 25 else "subset",
        "versions": {
            "cyver": importlib.metadata.version("cyver"),
            "pydantic_ai": importlib.metadata.version("pydantic-ai"),
            "typesafe_sdk": importlib.metadata.version("typesafe-sdk"),
        },
        "inputs": {
            "question_only_path": str(QUESTIONS),
            "question_sha256": _file_sha(QUESTIONS),
            "references_loaded_only_after_execution": True,
            "semantic_oracles_loaded_only_after_execution": True,
        },
        "deployment": deployment.model_dump(mode="json"),
        "catalog": [piece.public() for piece in CATALOG],
        "catalog_entry_count": len(CATALOG),
        "boundaries": {
            "model_selects_semantics_only": True,
            "compiler_generates_parameter_names": True,
            "compiler_generates_all_output_fields": True,
            "compiler_hydrates_each_relationship_independently": True,
            "role_only_reporting_uses_shared_context_by_deterministic_rule": True,
            "vectors_omitted_from_context_serialization": True,
            "references_available_before_execution": False,
            "model_visible_forbidden_term_hits": {
                term: sum(term in prompt for prompt in model_visible_prompts)
                for term in FORBIDDEN_MODEL_TERMS
            },
        },
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "cases": records,
        "summary": _summary(records),
        "model_usage_by_stage": usage,
        "model_request_count": sum(stage["requests"] for stage in usage.values()),
        "model_total_tokens": sum(stage["total_tokens"] for stage in usage.values()),
        "jev_selector_telemetry": _jev_telemetry(records)
        if args.selector in {"jev-filtered", "jev-staged"}
        else None,
        "baseline": {
            "commit": "30d72c4488ba35ca81f4b35eae8916b6a91d5c9b",
            "executed": 14,
            "nonempty": 14,
            "exact": 10,
            "over_broad": 4,
            "stopped": 11,
            "elapsed_seconds": 925.12,
            "requests": 138,
            "tokens": 289051,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_jsonable(report), indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--query-timeout", type=float, default=30.0)
    parser.add_argument(
        "--deployment", choices=("local", "openrouter"), default="local"
    )
    parser.add_argument("--model")
    parser.add_argument(
        "--schema-filter", choices=("pydantic", "jev"), default="pydantic"
    )
    parser.add_argument(
        "--schema-threshold",
        type=float,
        default=DEFAULT_SCHEMA_THRESHOLD,
        help="Experimental Jev schema cutoff; independent of the frozen fragment cutoff 0.52",
    )
    parser.add_argument(
        "--selector",
        choices=("pydantic", "jev", "jev-filtered", "jev-staged"),
        default="pydantic",
    )
    args = parser.parse_args()
    try:
        validate_threshold(args.schema_threshold)
    except ValueError as error:
        parser.error(str(error))
    report = run(args)
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
