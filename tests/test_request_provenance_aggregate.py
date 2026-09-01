"""Evaluation Run request provenance aggregates at the report boundary."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from pydantic_evals.reporting import EvaluationReport, ReportCase

from knowledge_map.evaluation import aggregate_request_provenance, write_report
from knowledge_map.schemas import DeploymentKind, ModelDeployment


def _case(name: str, records: list[dict[str, object]]) -> ReportCase:
    return ReportCase(
        name=name,
        inputs=None,
        metadata=None,
        expected_output=None,
        output=None,
        metrics={},
        attributes={"request_provenance": records},
        scores={},
        labels={},
        assertions={},
        task_duration=0.0,
        total_duration=0.0,
    )


def _request(
    *,
    deployment: str = "openrouter",
    provider: str | None,
    is_byok: bool | None,
    input_tokens: int | None,
    output_tokens: int | None,
    reasoning_tokens: int | None,
    cache_write_tokens: int | None,
    cache_read_tokens: int | None,
    total_tokens: int | None,
    charged_cost: Decimal | None,
    upstream_cost: Decimal | None,
    attempts: int,
    retry_count: int,
) -> dict[str, object]:
    return {
        "case_id": "authored-case",
        "request_sequence": 1,
        "deployment": deployment,
        "requested_model": "requested/model",
        "returned_model": "returned/model",
        "downstream_provider": provider,
        "generation_id": "generation",
        "is_byok": is_byok,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cache_read_tokens": cache_read_tokens,
        "total_tokens": total_tokens,
        "charged_cost": charged_cost,
        "upstream_cost": upstream_cost,
        "route_attempts": None,
        "attempts": attempts,
        "retry_count": retry_count,
    }


def test_written_report_serializes_mixed_request_provenance_aggregate(
    tmp_path: Path,
) -> None:
    local = _request(
        deployment="llama.cpp",
        provider=None,
        is_byok=None,
        input_tokens=2,
        output_tokens=3,
        reasoning_tokens=None,
        cache_write_tokens=None,
        cache_read_tokens=None,
        total_tokens=5,
        charged_cost=None,
        upstream_cost=None,
        attempts=1,
        retry_count=0,
    )
    byok = _request(
        provider="google-ai-studio/vertex",
        is_byok=True,
        input_tokens=10,
        output_tokens=4,
        reasoning_tokens=2,
        cache_write_tokens=None,
        cache_read_tokens=1,
        total_tokens=16,
        charged_cost=Decimal("0.0012"),
        upstream_cost=Decimal("0.0008"),
        attempts=2,
        retry_count=1,
    )
    funded = _request(
        provider="openai/hosted",
        is_byok=False,
        input_tokens=None,
        output_tokens=6,
        reasoning_tokens=3,
        cache_write_tokens=2,
        cache_read_tokens=None,
        total_tokens=None,
        charged_cost=Decimal("0.0023"),
        upstream_cost=None,
        attempts=1,
        retry_count=0,
    )
    unavailable = _request(
        provider=None,
        is_byok=None,
        input_tokens=None,
        output_tokens=None,
        reasoning_tokens=None,
        cache_write_tokens=None,
        cache_read_tokens=None,
        total_tokens=None,
        charged_cost=None,
        upstream_cost=None,
        attempts=3,
        retry_count=2,
    )
    report = EvaluationReport(
        name="provenance",
        cases=[_case("case-b", [byok, unavailable]), _case("case-a", [local, funded])],
    )

    path = write_report(
        report,
        task="provenance",
        deployment=ModelDeployment(kind=DeploymentKind.LOCAL, model="local/model"),
        gold_set_path=tmp_path / "gold.yaml",
        root=tmp_path / "reports",
    )

    document = json.loads(path.read_text())

    assert document["report"]["request_provenance_aggregate"] == {
        "input_tokens": 12,
        "output_tokens": 13,
        "reasoning_tokens": 5,
        "cache_write_tokens": 2,
        "cache_read_tokens": 1,
        "total_tokens": 21,
        "charged_cost": "0.0035",
        "upstream_cost": "0.0008",
        "attempts": 7,
        "retry_count": 3,
        "request_counts": [
            {"downstream_provider": None, "is_byok": None, "count": 2},
            {
                "downstream_provider": "google-ai-studio/vertex",
                "is_byok": True,
                "count": 1,
            },
            {"downstream_provider": "openai/hosted", "is_byok": False, "count": 1},
        ],
    }
    assert report.cases[0].attributes["request_provenance"] == [byok, unavailable]
    assert report.cases[1].attributes["request_provenance"] == [local, funded]


def test_request_provenance_aggregate_is_order_independent_and_keeps_missing_values() -> (
    None
):
    provider_b = _request(
        provider="provider-b",
        is_byok=False,
        input_tokens=4,
        output_tokens=None,
        reasoning_tokens=None,
        cache_write_tokens=None,
        cache_read_tokens=None,
        total_tokens=None,
        charged_cost=None,
        upstream_cost=Decimal("0.20"),
        attempts=2,
        retry_count=1,
    )
    unavailable = _request(
        provider=None,
        is_byok=None,
        input_tokens=None,
        output_tokens=None,
        reasoning_tokens=None,
        cache_write_tokens=None,
        cache_read_tokens=None,
        total_tokens=None,
        charged_cost=None,
        upstream_cost=None,
        attempts=1,
        retry_count=0,
    )
    provider_a = _request(
        provider="provider-a",
        is_byok=True,
        input_tokens=None,
        output_tokens=None,
        reasoning_tokens=None,
        cache_write_tokens=None,
        cache_read_tokens=None,
        total_tokens=None,
        charged_cost=None,
        upstream_cost=None,
        attempts=1,
        retry_count=0,
    )
    first = EvaluationReport(
        name="provenance",
        cases=[
            _case("case-z", [provider_b]),
            _case("case-a", [unavailable, provider_a]),
        ],
    )
    second = EvaluationReport(
        name="provenance",
        cases=[
            _case("case-a", [provider_a, unavailable]),
            _case("case-z", [provider_b]),
        ],
    )

    expected = {
        "input_tokens": 4,
        "output_tokens": None,
        "reasoning_tokens": None,
        "cache_write_tokens": None,
        "cache_read_tokens": None,
        "total_tokens": None,
        "charged_cost": None,
        "upstream_cost": Decimal("0.20"),
        "attempts": 4,
        "retry_count": 1,
        "request_counts": [
            {"downstream_provider": None, "is_byok": None, "count": 1},
            {"downstream_provider": "provider-a", "is_byok": True, "count": 1},
            {"downstream_provider": "provider-b", "is_byok": False, "count": 1},
        ],
    }

    assert aggregate_request_provenance(first).as_dict() == expected
    assert aggregate_request_provenance(second).as_dict() == expected
