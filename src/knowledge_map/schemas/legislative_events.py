"""Legislative Event dates as they cross the Graph Database Adapter boundary.

Per ADR 0002 the adapters accept domain models, not raw structures: the date is
resolved in ``core.legislative_events`` and the adapter writes what it is given.

An event absent from the map is not an event resolved to nothing — the first means
none was extracted and no date properties are written, the second is a failed
resolution carrying flags that say so.
"""

from pydantic import BaseModel, Field


class LegislativeEventDate(BaseModel):
    """The date a single Legislative Event resolved to, and how it was reached.

    Flags follow Bill Session Resolution's convention. These are properties and
    nothing more — **the date never enters the key**, deliberately; see CONTEXT.md.
    """

    date: str | None = None
    #: The article stated this date outright.
    date_verified: bool = False
    #: The article stated no date, so its publication day stood in.
    date_inferred: bool = False
    #: Neither route produced a date a human should trust unreviewed.
    needs_review: bool = False

    def graph_properties(self) -> dict[str, object]:
        """The date properties as they are written onto a Legislative Event node."""
        return self.model_dump()


class LegislativeEventDates(BaseModel):
    """Every Legislative Event dated for one Source Article, keyed by event name."""

    by_name: dict[str, LegislativeEventDate] = Field(default_factory=dict)

    def get(self, name: str | None) -> LegislativeEventDate | None:
        """Return the date for ``name``, or ``None`` if it has none."""
        if name is None:
            return None
        return self.by_name.get(name)
