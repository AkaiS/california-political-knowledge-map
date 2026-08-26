"""Declaring where the news ontology departs from the primary ontology.

Divergences are declared in ``news.py``, rendered into ``news-ontology.md``,
and checked by conformance.  Declare one only for an *unresolved* gap that
needs an authoritative source to close, in either direction; a transformation
we performed ourselves is recorded as that transformation instead, the way
``ShortcutRule`` is.

A dropped property is declared here and subtracted from ``news.PROPERTIES``,
so the two cannot drift apart.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Divergence:
    """A property on which the news ontology parts from the primary ontology.

    ``reason`` says why the gap is unresolved, not how to fix it.  The
    direction carries no field; ``gap_directions`` reads it off the primary
    ontology.
    """

    property_name: str
    applies_to: frozenset[str]
    reason: str


#: The two directions a divergence can part in, read off the primary ontology
#: rather than declared again: a property it declares is one news drops; one it
#: does not is one a news write path stamps.
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
