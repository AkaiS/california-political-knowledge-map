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


def normalize_bill_number(value: object) -> str | None:
    """Keep the old internal helper name as an alias for designation parsing."""
    return parse_bill_designation(value)


def _publication_session(published_date: str | None) -> str | None:
    if not published_date:
        return None
    try:
        year = datetime.fromisoformat(published_date.replace("Z", "+00:00")).year
    except ValueError:
        return None
    start = year if year % 2 else year - 1
    return f"{start}-{start + 1}"


def resolve_bill_sessions(
    article: SourceArticle,
    extractions: list[ExtractionResult],
) -> BillSessionResolutions:
    """Resolve every extracted bill number once for an entire Source Article."""
    linked_sessions: dict[str, set[str]] = {}
    for link in article.links:
        parsed = parse_bill_url(link.url)
        if parsed is not None:
            session, _chamber, number = parsed
            linked_sessions.setdefault(number, set()).add(session)

    bill_designations = {
        designation
        for extraction in extractions
        for node in extraction.nodes
        if node.label == "Bill"
        if (designation := parse_bill_designation(node.name))
    }
    inferred_session = _publication_session(article.published_date)
    resolved: dict[str, BillSessionResolution] = {}
    for designation in bill_designations:
        sessions = linked_sessions.get(designation, set())
        if len(sessions) == 1:
            resolved[designation] = BillSessionResolution(
                number=designation,
                session=next(iter(sessions)),
                session_verified=True,
            )
        elif len(sessions) > 1:
            resolved[designation] = BillSessionResolution(
                number=designation,
                needs_review=True,
            )
        else:
            resolved[designation] = BillSessionResolution(
                number=designation,
                session=inferred_session,
                session_inferred=inferred_session is not None,
                needs_review=inferred_session is None,
            )
    return BillSessionResolutions(by_number=resolved)
