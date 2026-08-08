"""Declaring where the news ontology departs from the primary ontology.

The news ontology is closed: it holds the structures a news article can actually
produce. It does not match the primary ontology, because prose carries less than the
primary ontology expects. This module names that gap so it can be declared in
``news.py``, rendered into ``news-ontology.md``, and checked by conformance.

A ``Divergence`` is an *unresolved* gap: news could not supply what the primary
ontology declares, and no record we hold can settle it. Closing one needs an
authoritative source, so the declaration says only what is provisional and why — it
does not describe the fix.

A transformation we performed ourselves is not a divergence. Those are recorded as
the transformation, which holds enough to reverse itself; the news ontology's
``ShortcutRule`` is one such record.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Divergence:
    """A property on which a source ontology parts from the primary ontology.

    Either the source's write path stamps one the primary ontology does not declare,
    or the primary ontology declares one the source cannot supply. Both are gaps only
    an authoritative record can close.
    """

    property_name: str
    applies_to: frozenset[str]
    reason: str


def assert_divergences_are_unresolved_gaps(
    divergences: tuple[Divergence, ...],
    declared_items: frozenset[str] | set[str],
    primary_properties: dict[str, frozenset[str]] | None = None,
) -> None:
    """Check a divergence table against the ontology it diverges from.

    ``declared_items`` are the labels or relationship types the source ontology
    declares. ``primary_properties`` is supplied for node divergences only: a
    property the primary ontology already declares for a label is not a gap.
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

        if primary_properties is None:
            continue
        for item in divergence.applies_to:
            assert divergence.property_name not in primary_properties[item], (
                f"{item}.{divergence.property_name} is declared in the primary "
                "ontology, so it is not a divergence — remove it"
            )
