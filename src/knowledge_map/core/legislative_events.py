"""Resolve Legislative Event dates from Source Article metadata.

Ingestion collapses: nodes onto a shared key, edges onto a Claim Key. So a value
that bears on identity is resolved once per Source Article, before anything is
persisted, and every Article Chunk is handed the same answer — resolved per chunk
it would be written repeatedly onto one node, and the last chunk in would win.

A Legislative Event's date is one such value. It stays out of the node key, which
is the name alone, but it is what a later reconciliation against an authoritative
legislative record joins on, so the event carries a date even where the article
stated none: the publication day stands in, flagged inferred rather than verified.
Contradiction is not resolved here — two chunks stating different dates for one
event go to review, since preferring either would restore the order-dependence.
"""

from datetime import datetime

from knowledge_map.ontology.properties import normalize_date
from knowledge_map.schemas import (
    ExtractionResult,
    LegislativeEventDate,
    LegislativeEventDates,
)

EVENT_LABEL = "LegislativeEvent"


def _publication_day(published_date: str | None) -> str | None:
    """The article's publication day, as a calendar date."""

    if not published_date:
        return None
    calendar_date = normalize_date(published_date)
    if calendar_date is not None:
        return calendar_date
    try:
        return datetime.fromisoformat(published_date.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def resolve_event_date(
    stated_dates: object, published_date: str | None
) -> LegislativeEventDate:
    """Settle one event's date from every date the article stated for it."""

    if not isinstance(stated_dates, (list, tuple, set)):
        stated_dates = [stated_dates]
    verified = {
        normalized
        for stated in stated_dates
        if (normalized := normalize_date(stated)) is not None
    }
    if len(verified) == 1:
        return LegislativeEventDate(date=next(iter(verified)), date_verified=True)
    if len(verified) > 1:
        return LegislativeEventDate(needs_review=True)
    inferred = _publication_day(published_date)
    return LegislativeEventDate(
        date=inferred,
        date_inferred=inferred is not None,
        needs_review=inferred is None,
    )


def resolve_legislative_event_dates(
    extractions: list[ExtractionResult], published_date: str | None
) -> LegislativeEventDates:
    """Date every Legislative Event across an article's extractions, by name."""

    stated_by_name: dict[str, list[object]] = {}
    for extraction in extractions:
        for node in extraction.nodes:
            if node.label == EVENT_LABEL:
                stated_by_name.setdefault(node.name, []).append(
                    node.properties.get("date")
                )
    return LegislativeEventDates(by_name={
        name: resolve_event_date(stated, published_date)
        for name, stated in stated_by_name.items()
    })
