"""Aggregate request provenance without altering per-case evidence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from math import fsum
from typing import Any

from pydantic_evals.reporting import EvaluationReport


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
    rate_limit_wait: float
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
            "rate_limit_wait": self.rate_limit_wait,
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
        provider = _optional_provider(record.get("downstream_provider"))
        is_byok = _optional_bool(record.get("is_byok"))
        key = (provider, is_byok)
        counts[key] = counts.get(key, 0) + 1

    return RequestProvenanceAggregate(
        input_tokens=_sum_int(records, "input_tokens"),
        output_tokens=_sum_int(records, "output_tokens"),
        reasoning_tokens=_sum_int(records, "reasoning_tokens"),
        cache_write_tokens=_sum_int(records, "cache_write_tokens"),
        cache_read_tokens=_sum_int(records, "cache_read_tokens"),
        total_tokens=_sum_int(records, "total_tokens"),
        charged_cost=_sum_decimal(records, "charged_cost"),
        upstream_cost=_sum_decimal(records, "upstream_cost"),
        attempts=sum(_required_int(record, "attempts") for record in records),
        retry_count=sum(_required_int(record, "retry_count") for record in records),
        rate_limit_wait=fsum(
            _required_number(record, "rate_limit_wait") for record in records
        ),
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
) -> Iterable[Mapping[str, object]]:
    for case in report.cases:
        attributes = getattr(case, "attributes", None)
        if isinstance(attributes, Mapping):
            yield from _records_from(attributes.get("request_provenance", ()))
    for failure in getattr(report, "failures", ()):
        yield from _records_from(getattr(failure, "request_provenance", ()))


def _records_from(records: Any) -> Iterable[Mapping[str, object]]:
    if records is None:
        return
    for record in records:
        if isinstance(record, Mapping):
            yield record
            continue
        as_dict = getattr(record, "as_dict", None)
        if callable(as_dict):
            converted = as_dict()
            if isinstance(converted, Mapping):
                yield converted
                continue
        raise TypeError("request provenance evidence must be a mapping")


def _sum_int(records: list[Mapping[str, object]], field: str) -> int | None:
    values = [value for record in records if (value := record.get(field)) is not None]
    if not values:
        return None
    return sum(_typed_int(value, field) for value in values)


def _sum_decimal(records: list[Mapping[str, object]], field: str) -> Decimal | None:
    values = [value for record in records if (value := record.get(field)) is not None]
    if not values:
        return None
    return sum((_typed_decimal(value, field) for value in values), Decimal(0))


def _required_int(record: Mapping[str, object], field: str) -> int:
    value = record.get(field)
    if value is None:
        raise ValueError(f"request provenance is missing required {field}")
    return _typed_int(value, field)


def _required_number(record: Mapping[str, object], field: str) -> float:
    value = record.get(field)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"request provenance has invalid required {field}")
    return float(value)


def _typed_int(value: object, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f"request provenance has invalid {field}")
    return value


def _typed_decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"request provenance has invalid {field}")
    return value


def _optional_provider(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("request provenance has invalid downstream_provider")
    return value


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TypeError("request provenance has invalid is_byok")
    return value


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
