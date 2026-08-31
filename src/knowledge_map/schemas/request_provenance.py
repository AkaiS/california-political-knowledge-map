"""Typed evidence for one model request in an Evaluation Case."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, fields
from decimal import Decimal
from typing import ClassVar


@dataclass(frozen=True, eq=False)
class ModelRequestProvenance(Mapping[str, object]):
    """Safe route, usage, and cost facts for one model response in a case."""

    case_id: str
    request_sequence: int
    deployment: str
    requested_model: str
    returned_model: str | None
    downstream_provider: str | None
    generation_id: str | None
    is_byok: bool | None
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    cache_write_tokens: int | None
    cache_read_tokens: int | None
    total_tokens: int | None
    charged_cost: Decimal | None
    upstream_cost: Decimal | None
    route_attempts: int | None
    attempts: int
    retry_count: int
    rate_limit_wait: float

    _FIELD_NAMES: ClassVar[tuple[str, ...]]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ModelRequestProvenance":
        """Validate report-shaped evidence at the typed aggregation boundary."""

        return cls(
            case_id=_required_str(value, "case_id"),
            request_sequence=_required_int(value, "request_sequence"),
            deployment=_required_str(value, "deployment"),
            requested_model=_required_str(value, "requested_model"),
            returned_model=_optional_str(value, "returned_model"),
            downstream_provider=_optional_str(value, "downstream_provider"),
            generation_id=_optional_str(value, "generation_id"),
            is_byok=_optional_bool(value, "is_byok"),
            input_tokens=_optional_int(value, "input_tokens"),
            output_tokens=_optional_int(value, "output_tokens"),
            reasoning_tokens=_optional_int(value, "reasoning_tokens"),
            cache_write_tokens=_optional_int(value, "cache_write_tokens"),
            cache_read_tokens=_optional_int(value, "cache_read_tokens"),
            total_tokens=_optional_int(value, "total_tokens"),
            charged_cost=_optional_decimal(value, "charged_cost"),
            upstream_cost=_optional_decimal(value, "upstream_cost"),
            route_attempts=_optional_int(value, "route_attempts"),
            attempts=_required_int(value, "attempts"),
            retry_count=_required_int(value, "retry_count"),
            rate_limit_wait=_required_number(value, "rate_limit_wait"),
        )

    def as_dict(self) -> dict[str, object]:
        """Return the report representation without changing field types."""

        return {name: getattr(self, name) for name in self._FIELD_NAMES}

    def __getitem__(self, key: str) -> object:
        if key not in self._FIELD_NAMES:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._FIELD_NAMES)

    def __len__(self) -> int:
        return len(self._FIELD_NAMES)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ModelRequestProvenance):
            return self.as_dict() == other.as_dict()
        if isinstance(other, Mapping):
            return self.as_dict() == dict(other)
        return NotImplemented


ModelRequestProvenance._FIELD_NAMES = tuple(
    field.name for field in fields(ModelRequestProvenance)
)


def _value(record: Mapping[str, object], field: str) -> object:
    if field not in record:
        raise ValueError(f"request provenance is missing required {field}")
    return record[field]


def _required_str(record: Mapping[str, object], field: str) -> str:
    value = _value(record, field)
    if not isinstance(value, str):
        raise TypeError(f"request provenance has invalid {field}")
    return value


def _optional_str(record: Mapping[str, object], field: str) -> str | None:
    value = _value(record, field)
    if value is not None and not isinstance(value, str):
        raise TypeError(f"request provenance has invalid {field}")
    return value


def _required_int(record: Mapping[str, object], field: str) -> int:
    value = _value(record, field)
    if type(value) is not int:
        raise TypeError(f"request provenance has invalid {field}")
    return value


def _optional_int(record: Mapping[str, object], field: str) -> int | None:
    value = _value(record, field)
    if value is not None and type(value) is not int:
        raise TypeError(f"request provenance has invalid {field}")
    return value


def _optional_decimal(record: Mapping[str, object], field: str) -> Decimal | None:
    value = _value(record, field)
    if value is not None and not isinstance(value, Decimal):
        raise TypeError(f"request provenance has invalid {field}")
    return value


def _optional_bool(record: Mapping[str, object], field: str) -> bool | None:
    value = _value(record, field)
    if value is not None and not isinstance(value, bool):
        raise TypeError(f"request provenance has invalid {field}")
    return value


def _required_number(record: Mapping[str, object], field: str) -> float:
    value = _value(record, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"request provenance has invalid {field}")
    return float(value)
