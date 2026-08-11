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

    dates = resolve_legislative_event_dates([extraction], "2024-01-17T09:00:00Z")

    assert set(dates.by_name) == {"Assembly floor vote on AB 218"}
    assert dates.get("AB 218") is None
    assert dates.get("Assembly floor vote on AB 218").date == "2024-01-15"


def _event(name: str, date: str | None = None):
    return Node(
        name=name,
        label="LegislativeEvent",
        properties={"date": date} if date is not None else {},
    )


def test_a_date_stated_in_one_chunk_holds_for_the_event_named_in_others():
    dated = ExtractionResult(nodes=[_event("Assembly floor vote on AB 218", "January 15, 2024")])
    undated = ExtractionResult(nodes=[_event("Assembly floor vote on AB 218")])

    for extractions in ([dated, undated], [undated, dated]):
        date = resolve_legislative_event_dates(
            extractions, "2024-01-17T09:00:00Z"
        ).get("Assembly floor vote on AB 218")

        assert date.date == "2024-01-15"
        assert date.date_verified is True
        assert date.date_inferred is False


def test_two_chunks_stating_different_dates_for_one_event_need_review():
    extractions = [
        ExtractionResult(nodes=[_event("Assembly floor vote on AB 218", "January 15, 2024")]),
        ExtractionResult(nodes=[_event("Assembly floor vote on AB 218", "January 16, 2024")]),
    ]

    date = resolve_legislative_event_dates(
        extractions, "2024-01-17T09:00:00Z"
    ).get("Assembly floor vote on AB 218")

    assert date.date is None
    assert date.date_verified is False
    assert date.date_inferred is False
    assert date.needs_review is True


def test_chunks_restating_the_same_date_leave_it_verified():
    extractions = [
        ExtractionResult(nodes=[_event("Assembly floor vote on AB 218", "January 15, 2024")]),
        ExtractionResult(nodes=[_event("Assembly floor vote on AB 218", "2024-01-15")]),
    ]

    date = resolve_legislative_event_dates(
        extractions, "2024-01-17T09:00:00Z"
    ).get("Assembly floor vote on AB 218")

    assert date.date == "2024-01-15"
    assert date.date_verified is True
    assert date.needs_review is False


def test_resolution_does_not_touch_the_recorded_extraction():
    # The extraction the pipeline records stays as the model produced it; only
    # what reaches the graph carries the resolution.
    extraction = ExtractionResult(nodes=[
        Node(name="Assembly floor vote on AB 218", label="LegislativeEvent", properties={}),
    ])

    resolve_legislative_event_dates([extraction], "2024-01-17T09:00:00Z")

    assert extraction.nodes[0].properties == {}
