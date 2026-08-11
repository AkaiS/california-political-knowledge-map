"""Resolve Legislative Event dates from Source Article metadata."""

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
    stated_date: object, published_date: str | None
) -> LegislativeEventDate:
    """When a Legislative Event happened, and how well we know it.

    A later reconciliation against an authoritative legislative record joins on
    date and bill, so the event has to carry a date even when the article never
    stated one. Where the article states one, that is the date and it is
    *verified*; otherwise the article's publication day stands in and is flagged
    *inferred*, because a story usually reports an event within a day or two of
    it happening and a near date is what makes the join possible at all.
    """

    verified = normalize_date(stated_date)
    if verified is not None:
        return LegislativeEventDate(date=verified, date_verified=True)
    inferred = _publication_day(published_date)
    return LegislativeEventDate(
        date=inferred,
        date_inferred=inferred is not None,
        needs_review=inferred is None,
    )


def resolve_legislative_event_dates(
    extraction: ExtractionResult, published_date: str | None
) -> LegislativeEventDates:
    """Date every Legislative Event in one extraction, keyed by event name.

    The name is what the adapter has to hand when it writes the node, and it is
    what the event's key is derived from, so it is what the map is keyed by.
    """

    return LegislativeEventDates(by_name={
        node.name: resolve_event_date(node.properties.get("date"), published_date)
        for node in extraction.nodes
        if node.label == EVENT_LABEL
    })
