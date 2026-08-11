from knowledge_map.core.legislative_events import (
    resolve_event_date,
    resolve_legislative_event_dates,
)
from knowledge_map.schemas import ExtractionResult, Node


def test_a_stated_event_date_is_recorded_and_flagged_verified():
    date = resolve_event_date("January 15, 2024", "2024-01-17T09:00:00Z")

    assert date.date == "2024-01-15"
    assert date.date_verified is True
    assert date.date_inferred is False
    assert date.needs_review is False


def test_an_undated_event_falls_back_to_the_publication_date_as_inferred():
    date = resolve_event_date(None, "2024-01-17T09:00:00Z")

    # A story reports an event within a day or two, so the publication date is
    # near enough for a later join and never good enough for the key.
    assert date.date == "2024-01-17"
    assert date.date_verified is False
    assert date.date_inferred is True
    assert date.needs_review is False


def test_an_event_with_no_date_anywhere_is_flagged_for_review():
    date = resolve_event_date(None, None)

    assert date.date is None
    assert date.date_verified is False
    assert date.date_inferred is False
    assert date.needs_review is True


def test_an_unparseable_publication_date_settles_nothing():
    date = resolve_event_date(None, "sometime last spring")

    assert date.date is None
    assert date.needs_review is True


def test_only_legislative_events_are_dated():
    extraction = ExtractionResult(nodes=[
        Node(name="Assembly floor vote on AB 218", label="LegislativeEvent",
             properties={"date": "January 15, 2024"}),
        Node(name="AB 218", label="Bill", properties={"date": "January 15, 2024"}),
    ])

    dates = resolve_legislative_event_dates(extraction, "2024-01-17T09:00:00Z")

    assert set(dates.by_name) == {"Assembly floor vote on AB 218"}
    assert dates.get("AB 218") is None
    assert dates.get("Assembly floor vote on AB 218").date == "2024-01-15"


def test_resolution_does_not_touch_the_recorded_extraction():
    # The extraction the pipeline records stays as the model produced it; only
    # what reaches the graph carries the resolution.
    extraction = ExtractionResult(nodes=[
        Node(name="Assembly floor vote on AB 218", label="LegislativeEvent", properties={}),
    ])

    resolve_legislative_event_dates(extraction, "2024-01-17T09:00:00Z")

    assert extraction.nodes[0].properties == {}
