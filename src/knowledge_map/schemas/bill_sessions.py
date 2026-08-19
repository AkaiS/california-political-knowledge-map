"""Bill Session Resolution as it crosses the Graph Database Adapter boundary.

Per ADR 0002 the adapters accept domain models, not raw structures. A bill's
designation and session are resolved once per Source Article and handed to the
adapter as :class:`BillSessionResolutions`: the properties themselves plus the
flags that say how the session was arrived at, which the adapter writes onto the
Bill and folds into its primary key.

A number absent from the resolution map is not the same as a number resolved to
nothing. The former means no Bill by that number was extracted, and the adapter
writes no session properties at all; the latter is a resolution that failed and
carries its own flags saying so.
"""

from pydantic import BaseModel, Field


class BillSessionResolution(BaseModel):
    """The Bill Designation and session a bill resolved to, and how it was reached."""

    number: str | None = None
    session: str | None = None
    #: A bill link in the article named this session outright.
    session_verified: bool = False
    #: No link named a session, so the article's publication date implied one.
    session_inferred: bool = False
    #: Neither route produced a session a human should trust unreviewed.
    needs_review: bool = False

    def graph_properties(self) -> dict[str, object]:
        """The resolved properties as they are written onto a Bill node."""
        return self.model_dump()


class BillSessionResolutions(BaseModel):
    """Every Bill Designation resolved for one Source Article, keyed by designation."""

    by_number: dict[str, BillSessionResolution] = Field(default_factory=dict)

    def get(self, number: str | None) -> BillSessionResolution | None:
        """Return the resolution for ``number``, or ``None`` if it has none."""
        if number is None:
            return None
        return self.by_number.get(number)
