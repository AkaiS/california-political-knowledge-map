"""Declaring where a source-specific ontology departs from the primary ontology.

Every extraction source gets its own closed ontology — the structures that source
can actually produce. None of them will match the primary ontology exactly, because
each source carries less than the primary ontology expects. This module names that
gap so it can be declared, rendered, and checked the same way for every source.

A ``Divergence`` is an *unresolved* gap: the source could not supply what the primary
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
    """A property a source's write path stamps that the primary ontology lacks."""

    property_name: str
    applies_to: frozenset[str]
    reason: str


def properties_for(divergences: tuple[Divergence, ...], item: str) -> frozenset[str]:
    """Property names stamped on ``item``, a label or a relationship type."""
    return frozenset(
        divergence.property_name
        for divergence in divergences
        if item in divergence.applies_to
    )


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
