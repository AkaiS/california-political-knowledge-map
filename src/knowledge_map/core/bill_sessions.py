"""Resolve California bill sessions from Source Article metadata."""

import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from knowledge_map.schemas import (
    BillSessionResolution,
    BillSessionResolutions,
    ExtractionResult,
    SourceArticle,
)

_PATH_BILL = re.compile(r"/bills/ca_(\d{4})(\d{4})0([a-z]{2,3})(\d+)", re.IGNORECASE)
_QUERY_BILL = re.compile(r"^(\d{4})(\d{4})0([a-z]{2,3})(\d+)$", re.IGNORECASE)
_BILL_DESIGNATION = re.compile(
    r"\b(?P<chamber>SB|AB|SENATE\s+BILL|ASSEMBLY\s+BILL)"
    r"\s*[- ]?\s*(?P<digits>\d+)\b",
    re.IGNORECASE,
)
_DIGITS = re.compile(r"\d+")


def parse_bill_url(url: str) -> tuple[str, str, str] | None:
    """Return ``(session, chamber, number)`` for a known California bill URL."""
    parsed = urlparse(url)
    match = _PATH_BILL.search(parsed.path)
    if match is None:
        bill_ids = parse_qs(parsed.query).get("bill_id", [])
        match = _QUERY_BILL.fullmatch(bill_ids[0]) if bill_ids else None
    if match is None:
        return None
    start, end, chamber, digits = match.groups()
    chamber = chamber.upper()
    return f"{start}-{end}", chamber, f"{chamber} {int(digits)}"


def parse_bill_designation(value: object) -> str | None:
    """Parse one of California's four Bill Designation forms from a name."""
    if not isinstance(value, str):
        return None
    match = _BILL_DESIGNATION.search(value)
    if match is None:
        return None
    chamber = " ".join(match.group("chamber").upper().split())
    initials = "SB" if chamber in {"SB", "SENATE BILL"} else "AB"
    return f"{initials} {int(match.group('digits'))}"


def _publication_session(published_date: str | None) -> str | None:
    if not published_date:
        return None
    try:
        year = datetime.fromisoformat(published_date.replace("Z", "+00:00")).year
    except ValueError:
        return None
    start = year if year % 2 else year - 1
    return f"{start}-{start + 1}"


def _recover_bill_designation(
    name: str,
    article_designations: set[str],
) -> str | None:
    """Recover one designation from the digits in an otherwise unparsed name."""
    name_numbers = {
        digits.lstrip("0") or "0" for digits in _DIGITS.findall(name)
    }
    matches = {
        designation
        for designation in article_designations
        if designation.rsplit(" ", maxsplit=1)[1] in name_numbers
    }
    if len(matches) != 1:
        return None
    return next(iter(matches))


def resolve_bill_sessions(
    article: SourceArticle,
    extractions: list[ExtractionResult],
) -> BillSessionResolutions:
    """Resolve every extracted Bill once for an entire Source Article."""
    linked_sessions: dict[str, set[str]] = {}
    for link in article.links:
        parsed = parse_bill_url(link.url)
        if parsed is not None:
            session, _chamber, number = parsed
            linked_sessions.setdefault(number, set()).add(session)

    surfaces = {
        node.name
        for extraction in extractions
        for node in extraction.nodes
        if node.label == "Bill"
    }
    parsed_designations = {
        surface: parse_bill_designation(surface) for surface in surfaces
    }
    article_designations = {
        designation for designation in parsed_designations.values() if designation
    }
    inferred_session = _publication_session(article.published_date)
    resolved: dict[str, BillSessionResolution] = {}
    for surface in sorted(surfaces):
        designation = parsed_designations[surface]
        if designation is None:
            designation = _recover_bill_designation(surface, article_designations)
        if designation is None:
            resolved[surface] = BillSessionResolution(needs_review=True)
            continue

        sessions = linked_sessions.get(designation, set())
        if len(sessions) == 1:
            resolved[surface] = BillSessionResolution(
                name=designation,
                session=next(iter(sessions)),
                session_verified=True,
            )
        elif len(sessions) > 1:
            resolved[surface] = BillSessionResolution(
                name=designation,
                needs_review=True,
            )
        else:
            resolved[surface] = BillSessionResolution(
                name=designation,
                session=inferred_session,
                session_inferred=inferred_session is not None,
                needs_review=inferred_session is None,
            )
    return BillSessionResolutions(by_name=resolved)
