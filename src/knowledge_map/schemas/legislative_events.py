"""Legislative Event dates as they cross the Graph Database Adapter boundary.

Per ADR 0002 the adapters accept domain models, not raw structures. When a
Legislative Event happened — and how well we know it — is resolved in the core
and handed to the adapter as :class:`LegislativeEventDates`, so the adapter
never sees the article's raw publication date and never decides what a date
means. It looks the event up by name and writes the properties it is given.

An event absent from the map is not the same as an event resolved to nothing.
The former means no Legislative Event by that name was extracted, and the
adapter writes no date properties at all; the latter is a resolution that failed
and carries its own flags saying so.
"""

from pydantic import BaseModel, Field


class LegislativeEventDate(BaseModel):
    """The date a single Legislative Event resolved to, and how it was reached.

    The flags follow Bill Session Resolution's convention: a value, a verified
    flag, an inferred flag, and ``needs_review`` when nothing we hold settles it.

    These are properties and nothing more: **the date is never part of the key.**
    A wrong date in the key would conflate two distinct events, which nothing
    downstream can undo, whereas a name-derived key at worst fragments one event
    into two nodes that a later join on date and bill can merge back. Nor is the
    date keyed only when verified: that would give Legislative Events two
    identity shapes, and a later correct-date ingest can only find every node it
    must fix if there is one shape to look for.
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
    """Every Legislative Event dated for one extraction, keyed by event name."""

    by_name: dict[str, LegislativeEventDate] = Field(default_factory=dict)

    def get(self, name: str | None) -> LegislativeEventDate | None:
        """Return the date for ``name``, or ``None`` if it has none."""
        if name is None:
            return None
        return self.by_name.get(name)
