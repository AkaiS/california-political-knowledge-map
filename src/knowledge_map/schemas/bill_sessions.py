"""Bill Session Resolution as it crosses the Graph Database Adapter boundary.

Per ADR 0002 the adapters accept domain models, not raw structures. A bill's
designation and session are resolved once per Source Article and handed to the
adapter as :class:`BillSessionResolutions`: the properties themselves plus the
flags that say how the session was arrived at, which the adapter writes onto the
Bill and folds into its primary key.

The map is keyed by the surface string the article used. That lets resolution
represent a Bill whose surface string did not yield a designation as explicitly
as one that did: the failed resolution carries no name or session and sets
``needs_review``.
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

        Every extracted Bill is resolved, so a name with no entry is one the
        adapter was handed without resolution ever seeing it. That is the same
        state as a name that yielded nothing: unidentified, and needing review.
        Answering for every name keeps the adapter free of existence checks.
        """
        if name is None:
            return BillSessionResolution(needs_review=True)
        return self.by_name.get(name) or BillSessionResolution(needs_review=True)
