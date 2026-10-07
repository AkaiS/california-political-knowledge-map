# ruff: noqa: BLE001
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from neo4j import Query
from pydantic import BaseModel, ConfigDict, Field

from knowledge_map.ontology import news


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cypher: str
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    explanation: str


@dataclass(frozen=True)
class Case:
    opaque_id: str
    source_id: str
    question: str


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
    if hasattr(value, "items"):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _exception_capture(error):
    return {"type": type(error).__name__}


_WRITE_WORDS = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|FOREACH)\b",
    re.IGNORECASE,
)
# Restrict relationship parsing to an actual directed relationship pattern.
# Returned evidence lists also contain square brackets and map colons.
_REL = re.compile(r"-\[[^\]]*?:([^\]]+)\]->")
_NODE = re.compile(
    r"\(([A-Za-z_][A-Za-z0-9_]*)?((?::`?[A-Za-z_][A-Za-z0-9_]*`?)+)[^)]*\)"
)
_PARAMETER_WARNING = "Neo.ClientNotification.Statement.ParameterNotProvided"


def deterministic_errors(plan: QueryPlan) -> list[str]:
    cypher = plan.cypher.strip()
    errors: list[str] = []
    if ";" in cypher:
        errors.append("multiple statements or trailing semicolon are forbidden")
    if _WRITE_WORDS.search(cypher):
        errors.append("query contains a write clause")
    upper = cypher.upper()
    if "MATCH" not in upper or "RETURN" not in upper:
        errors.append("query must contain MATCH and RETURN")
    declared = set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", cypher))
    supplied = set(plan.parameters)
    errors.extend(f"missing parameter: {name}" for name in sorted(declared - supplied))
    if unused := sorted(supplied - declared):
        errors.append(f"unused parameters: {', '.join(unused)}")
    labels = {
        label
        for _, label_text in _NODE.findall(cypher)
        for label in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", label_text)
    }
    known_labels = set(news.LABELS) | set().union(*news.SUB_LABELS.values())
    errors.extend(
        f"unknown ontology label: {label}" for label in sorted(labels - known_labels)
    )
    relationships: set[str] = set()
    for expression in _REL.findall(cypher):
        relationships.update(
            re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression.split("{")[0])
        )
    errors.extend(
        f"unknown ontology relationship: {name}"
        for name in sorted(relationships - set(news.RELATIONSHIPS))
    )
    return list(dict.fromkeys(errors))


def _ontology_pattern_valid(plan: QueryPlan) -> bool:
    return not any(
        error.startswith("unknown ontology") for error in deterministic_errors(plan)
    )


def _explain(driver: Any, plan: QueryPlan, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with driver.session(default_access_mode="READ") as session:
            summary = session.run(
                Query("EXPLAIN " + plan.cypher, timeout=timeout), plan.parameters
            ).consume()
        return {
            "ok": summary.query_type == "r",
            "query_type": summary.query_type,
            "error": None
            if summary.query_type == "r"
            else "Neo4j did not classify the query as read-only",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except Exception as error:
        return {
            "ok": False,
            "query_type": None,
            "error": _exception_capture(error),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }


def validate_plan(
    driver: Any,
    validators: tuple[Any, Any, Any],
    plan: QueryPlan,
    timeout: float,
) -> dict[str, Any]:
    syntax_validator, schema_validator, properties_validator = validators
    deterministic = deterministic_errors(plan)
    parameter_complete = not any(
        error.startswith(("missing parameter", "unused parameters"))
        for error in deterministic
    )
    explain = _explain(driver, plan, timeout)
    raw: dict[str, Any] = {}
    for name, validator in (
        ("syntax", syntax_validator),
        ("schema", schema_validator),
        ("property", properties_validator),
    ):
        started = time.perf_counter()
        try:
            score, metadata = validator.validate(plan.cypher)
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
                "error": _exception_capture(error),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
    normalized = json.loads(json.dumps(raw))
    ignored_parameter_warnings: list[dict[str, Any]] = []
    if parameter_complete and explain["ok"]:
        syntax_metadata = normalized["syntax"]["metadata"]
        ignored_parameter_warnings = [
            item for item in syntax_metadata if item.get("code") == _PARAMETER_WARNING
        ]
        normalized["syntax"]["metadata"] = [
            item for item in syntax_metadata if item.get("code") != _PARAMETER_WARNING
        ]
        if raw["syntax"]["score"] is False and not normalized["syntax"]["metadata"]:
            normalized["syntax"]["score"] = True
    ontology_valid_unpopulated = (
        _ontology_pattern_valid(plan)
        and not raw["schema"]["error"]
        and raw["schema"]["score"] is not None
        and float(raw["schema"]["score"]) < 1.0
        and not any(
            item.get("code", "").startswith("Neo.ClientNotification.Statement.Unknown")
            for item in raw["schema"]["metadata"]
        )
    )
    normalized_errors = list(deterministic)
    if (
        not normalized["syntax"]["score"]
        or normalized["syntax"]["metadata"]
        or normalized["syntax"]["error"]
    ):
        normalized_errors.append("CyVer syntax validation failed")
    if (
        normalized["schema"]["score"] != 1
        or normalized["schema"]["metadata"]
        or normalized["schema"]["error"]
    ):
        normalized_errors.append("CyVer schema validation failed")
    property_score = normalized["property"]["score"]
    if (
        property_score not in (None, 1, 1.0)
        or normalized["property"]["metadata"]
        or normalized["property"]["error"]
    ):
        normalized_errors.append("CyVer property validation failed")
    if not explain["ok"]:
        normalized_errors.append(
            "parameter-aware Neo4j EXPLAIN failed or was not read-only"
        )
    return {
        "raw_cyver": raw,
        "normalized_cyver": normalized,
        "ignored_expected_parameter_warnings": ignored_parameter_warnings,
        "parameter_complete": parameter_complete,
        "deterministic_safety_errors": deterministic,
        "parameter_aware_explain": explain,
        "ontology_valid_but_unpopulated": ontology_valid_unpopulated,
        "errors": list(dict.fromkeys(normalized_errors)),
        "authorized": not normalized_errors,
    }


def _execute(driver: Any, plan: QueryPlan, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with driver.session(default_access_mode="READ") as session:
            rows = session.run(
                Query(plan.cypher, timeout=timeout), plan.parameters
            ).data()
        return {
            "ok": True,
            "rows": _jsonable(rows),
            "error": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except Exception as error:
        return {
            "ok": False,
            "rows": [],
            "error": _exception_capture(error),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
