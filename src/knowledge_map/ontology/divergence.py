"""Declaring where the news ontology departs from the primary ontology.

The news ontology is closed: it holds the structures a news article can actually
produce. It does not match the primary ontology, because prose carries less than the
primary ontology expects. This module names that gap so it can be declared in
``news.py``, rendered into ``news-ontology.md``, and checked by conformance.

A ``Divergence`` is an *unresolved* gap, in either direction: the primary ontology
declares a property news cannot supply, or a news write path stamps one the primary
ontology does not declare. Both are gaps no record we hold can settle. Closing one
needs an authoritative source, so the declaration says only what is provisional and
why — it does not describe the fix.

The two directions are one table on purpose. A dropped property is declared here and
subtracted from ``news.PROPERTIES``, so the ontology and the gap that explains it
cannot drift apart; a second table of dropped properties could contradict this one.

A transformation we performed ourselves is not a divergence. Those are recorded as
the transformation, which holds enough to reverse itself; the news ontology's
``ShortcutRule`` is one such record.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Divergence:
    """A property on which the news ontology parts from the primary ontology.

    Either the news write path stamps one the primary ontology does not declare, or
    the primary ontology declares one news cannot supply. Both are gaps only an
    authoritative record can close.

    Which of the two it is carries no field: it is read off the primary ontology by
    ``gap_directions``, because that is where the answer already lives.
    """

    property_name: str
    applies_to: frozenset[str]
    reason: str


#: The two directions a divergence can part in, derived from the primary ontology
#: rather than declared a second time on the ``Divergence`` itself. A property the
#: primary ontology declares is one news drops; a property it does not declare is
#: one a news write path stamps. Storing the direction would be a second copy of a
#: fact the primary ontology already holds, and the two could disagree.
NOT_SUPPLIED = "news cannot supply it"
STAMPED = "the write path stamps it"


def gap_directions(
    divergence: Divergence, primary_properties: dict[str, frozenset[str]]
) -> tuple[str, ...]:
    """Which way ``divergence`` parts from the primary ontology, per item.

    A divergence applies to a set of items, and nothing requires the direction to
    be the same for all of them — ``name`` already picks its labels by exactly this
    membership test. So this reports every direction present in the set rather than
    collapsing to one, which a stored field would have to do.
    """

    return tuple(
        sorted(
            {
                NOT_SUPPLIED
                if divergence.property_name in primary_properties.get(item, frozenset())
                else STAMPED
                for item in divergence.applies_to
            }
        )
    )


def assert_divergences_are_unresolved_gaps(
    divergences: tuple[Divergence, ...],
    declared_items: frozenset[str] | set[str],
) -> None:
    """Check a divergence table against the ontology it diverges from.

    ``declared_items`` are the labels or relationship types the source ontology
    declares. Which direction a divergence runs in is not checked here, because it
    is not a choice: it is read off the primary ontology by ``gap_directions``, and
    both directions are gaps.
    """

    for divergence in divergences:
        assert divergence.reason.strip(), (
            f"Divergence {divergence.property_name} states no reason"
        )
        assert divergence.applies_to, (
            f"Divergence {divergence.property_name} applies to nothing"
        )

        undeclared = divergence.applies_to - declared_items
        assert not undeclared, (
            f"Divergence {divergence.property_name} applies to items outside the "
            f"source ontology: {sorted(undeclared)}"
        )
