"""Aggregate request provenance without altering per-case evidence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic_evals.reporting import EvaluationReport

from knowledge_map.schemas import ModelRequestProvenance


@dataclass(frozen=True)
class RequestProvenanceCount:
    """Count requests sharing one observed provider and BYOK status."""

    downstream_provider: str | None
    is_byok: bool | None
    count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "downstream_provider": self.downstream_provider,
            "is_byok": self.is_byok,
            "count": self.count,
        }


@dataclass(frozen=True)
class RequestProvenanceAggregate:
    """Totals and request groups derived from a report's request evidence."""

    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    cache_write_tokens: int | None
    cache_read_tokens: int | None
    total_tokens: int | None
    charged_cost: Decimal | None
    upstream_cost: Decimal | None
    attempts: int
    retry_count: int
    request_counts: tuple[RequestProvenanceCount, ...]

    def as_dict(self) -> dict[str, object]:
        """Return the narrow report representation of the aggregate."""

        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "total_tokens": self.total_tokens,
            "charged_cost": self.charged_cost,
            "upstream_cost": self.upstream_cost,
            "attempts": self.attempts,
            "retry_count": self.retry_count,
            "request_counts": [count.as_dict() for count in self.request_counts],
        }


def aggregate_request_provenance(
    report: EvaluationReport[Any, Any, Any],
) -> RequestProvenanceAggregate:
    """Summarize the request evidence already attached to ``report``.

    ``None`` means no request supplied a value for an optional category. Values
    that are present are summed without reconstructing or estimating missing
    provider facts.
    """

    records = list(_report_records(report))
    counts: dict[tuple[str | None, bool | None], int] = {}
    for record in records:
        key = (record.downstream_provider, record.is_byok)
        counts[key] = counts.get(key, 0) + 1

    return RequestProvenanceAggregate(
        input_tokens=_sum_optional_int(record.input_tokens for record in records),
        output_tokens=_sum_optional_int(record.output_tokens for record in records),
        reasoning_tokens=_sum_optional_int(
            record.reasoning_tokens for record in records
        ),
        cache_write_tokens=_sum_optional_int(
            record.cache_write_tokens for record in records
        ),
        cache_read_tokens=_sum_optional_int(
            record.cache_read_tokens for record in records
        ),
        total_tokens=_sum_optional_int(record.total_tokens for record in records),
        charged_cost=_sum_optional_decimal(
            record.charged_cost for record in records
        ),
        upstream_cost=_sum_optional_decimal(
            record.upstream_cost for record in records
        ),
        attempts=sum(record.attempts for record in records),
        retry_count=sum(record.retry_count for record in records),
        request_counts=tuple(
            RequestProvenanceCount(
                downstream_provider=provider,
                is_byok=is_byok,
                count=count,
            )
            for (provider, is_byok), count in sorted(
                counts.items(), key=_request_count_sort_key
            )
        ),
    )


def _report_records(
    report: EvaluationReport[Any, Any, Any],
) -> Iterable[ModelRequestProvenance]:
    for case in report.cases:
        attributes = getattr(case, "attributes", None)
        if isinstance(attributes, Mapping):
            yield from _records_from(attributes.get("request_provenance", ()))
    for failure in getattr(report, "failures", ()):
        yield from _records_from(getattr(failure, "request_provenance", ()))


def _records_from(records: Any) -> Iterable[ModelRequestProvenance]:
    if records is None:
        return
    for record in records:
        if isinstance(record, ModelRequestProvenance):
            yield record
            continue
        if isinstance(record, Mapping):
            yield ModelRequestProvenance.from_mapping(record)
            continue
        raise TypeError("request provenance evidence must be typed or a mapping")


def _sum_optional_int(values: Iterable[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _sum_optional_decimal(values: Iterable[Decimal | None]) -> Decimal | None:
    present = [value for value in values if value is not None]
    return sum(present, Decimal(0)) if present else None


def _request_count_sort_key(
    item: tuple[tuple[str | None, bool | None], int],
) -> tuple[bool, str, bool, str]:
    (provider, is_byok), _count = item
    return (
        provider is not None,
        provider or "",
        is_byok is not None,
        str(is_byok),
    )
