"""Bill Session Resolution as it crosses the Graph Database Adapter boundary.

Resolve every Bill in a Source Article once, then hand the adapter one
:class:`BillSessionResolutions`; it writes the properties onto the Bill and
folds them into its primary key.

Keyed by the surface string the article used, so a Bill whose surface string
yielded no designation is represented as explicitly as one that did — carrying
no name or session, and ``needs_review``.
"""

from pydantic import BaseModel, Field


class BillSessionResolution(BaseModel):
    """The Bill Designation and session a bill resolved to, and how it was reached."""

    #: The Bill Designation, which is the Bill's name: `SB 623`, `AB 1751`.
    #: ``None`` where the extracted surface string yielded none.
    name: str | None = None
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
    """Every extracted Bill resolved for one Source Article, keyed by its name."""

    by_name: dict[str, BillSessionResolution] = Field(default_factory=dict)

    def get(self, name: str | None) -> BillSessionResolution:
        """Return the resolution for ``name``.

        Answers for every name, so the adapter needs no existence check: an
        unseen name resolves the same as one that yielded nothing.
        """
        if name is None:
            return BillSessionResolution(needs_review=True)
        return self.by_name.get(name) or BillSessionResolution(needs_review=True)
