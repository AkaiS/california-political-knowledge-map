"""Normalized shapes for relationship properties.

Relationship properties are open: an extractor may attach anything it believes an
article asserted, and the write path keeps it. What this module declares is the
shape of the few properties whose *value* carries the claim — the ones two articles
must agree on before their edges can be called the same edge.

Declaring a shape does not make a property required. It says: if you find one, it
looks like this. ``news.IDENTIFYING_PROPERTIES`` is where a property becomes
required, because there the value is what makes the relationship comparable at all.

A normalizer returns ``None`` when it cannot produce a canonical value. The write
path treats that exactly like an absent value: the claim is incomplete, so it is
flagged rather than keyed on a string nothing else will ever match.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

_MAGNITUDES = {
    "k": 1_000.0, "thousand": 1_000.0,
    "m": 1_000_000.0, "mm": 1_000_000.0, "million": 1_000_000.0,
    "b": 1_000_000_000.0, "bn": 1_000_000_000.0, "billion": 1_000_000_000.0,
}

_DATE_FORMATS = ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%m/%d/%Y")


@dataclass(frozen=True)
class PropertySpec:
    """The canonical form a relationship property takes when one is supplied.

    ``form`` is how the extraction prompt asks for the value, and ``example`` is a
    value written that way. A test normalizes every ``example``, so the prompt cannot
    ask for a form the write path would then throw away.
    """

    name: str
    normalize: Callable[[object], object | None]
    form: str
    example: str


def normalize_amount(value: object) -> float | None:
    """A currency figure as a float. ``"$6 million"``, ``"6M"``, ``6_000_000`` all agree."""

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    text = value.strip().lower().replace(",", "").replace("$", "").replace("usd", "")
    match = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*([a-z]*)", text.strip())
    if match is None:
        return None

    number, suffix = match.groups()
    if not suffix:
        return float(number)
    magnitude = _MAGNITUDES.get(suffix)
    return float(number) * magnitude if magnitude else None


def normalize_integer(value: object) -> int | None:
    """A whole number. A figure with a fractional part is not one."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    number = normalize_amount(value)
    if number is None or number != int(number):
        return None
    return int(number)


def normalize_date(value: object) -> str | None:
    """A calendar date as ``YYYY-MM-DD``. A year alone is not a date."""

    if not isinstance(value, str):
        return None
    text = value.strip()
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def enum_of(*allowed: str) -> Callable[[object], str | None]:
    """Normalize to one of ``allowed``, case-insensitively, or to ``None``."""

    permitted = {item.upper(): item for item in allowed}

    def normalize(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        return permitted.get(value.strip().upper())

    return normalize


def enum_spec(name: str, *allowed: str) -> PropertySpec:
    """A property restricted to a fixed vocabulary.

    The normalizer and the prompt wording are built from one list, so the prompt
    cannot advertise a value the write path rejects.
    """

    return PropertySpec(
        name=name,
        normalize=enum_of(*allowed),
        form="exactly one of " + ", ".join(f"`{item}`" for item in allowed),
        example=allowed[0],
    )


def normalize_text(value: object) -> str | None:
    """A non-empty string, whitespace-trimmed."""

    if not isinstance(value, str):
        return None
    return value.strip() or None
