"""Frozen ablation: remove the wording example from both peer descriptions."""

from collections import Counter
from dataclasses import fields, replace
import importlib


_MARKER = " This is the complete anchor-and-peer pattern for wording such as "
_PEER_VARIANTS = {"peer_source", "peer_target"}


def _assert_description_only(before, after):
    assert len(before) == len(after)
    changed = Counter()
    for old, new in zip(before, after, strict=True):
        assert type(old) is type(new)
        for field in fields(old):
            if field.name != "description":
                assert getattr(old, field.name) == getattr(new, field.name)
        if old.variant in _PEER_VARIANTS:
            first, separator, suffix = old.description.partition(_MARKER)
            assert separator and suffix.startswith("'other ")
            assert suffix.endswith(" entities alongside'.")
            assert new.description == first
            assert "two different" in first.lower()
            assert "recorded" in first
            assert "same" in first
            changed[old.variant] += 1
        else:
            assert old == new
    assert set(changed) == _PEER_VARIANTS
    assert changed["peer_source"] == changed["peer_target"]
    return dict(changed)


def apply(runner, staged, fragments):
    """Change peer prompt descriptions without changing their semantic shape."""
    filtered = importlib.import_module(staged.candidate_fragments.__module__)
    original = fragments.FRAGMENTS
    original_by_id = fragments.BY_FRAGMENT_ID
    original_relationships = fragments._relationship_fragments
    assert filtered.all_relationship_fragments is original_relationships

    # This schema exercises the existing candidate generator without eval data.
    labels = set()
    predicates = set()
    for piece in fragments.CATALOG:
        if piece.kind == "relationship":
            labels.update((piece.source_label.value, piece.target_label.value))
            predicates.update(predicate.value for predicate in piece.predicates)
        elif piece.kind in {"role", "filter"}:
            labels.add(piece.node_label.value)
    subgraph = filtered.normalize_schema(
        {"labels": sorted(labels), "relationships": sorted(predicates)}
    )
    candidates_before = filtered.candidate_fragments(subgraph)

    updated = tuple(
        replace(fragment, description=fragment.description.partition(_MARKER)[0])
        if fragment.variant in _PEER_VARIANTS
        else fragment
        for fragment in original
    )
    changed = _assert_description_only(original, updated)
    updated_by_id = {fragment.fragment_id: fragment for fragment in updated}
    relationship_entries = tuple(
        fragment for fragment in updated if fragment.competition_group is not None
    )
    assert tuple(fragment.fragment_id for fragment in original_relationships()) == tuple(
        fragment.fragment_id for fragment in relationship_entries
    )

    def relationship_fragments():
        yield from relationship_entries

    # Imported aliases must observe the replaced frozen entries too.
    for module in (runner, staged, fragments, filtered):
        for name, value in tuple(vars(module).items()):
            if value is original:
                setattr(module, name, updated)
            elif value is original_by_id:
                setattr(module, name, updated_by_id)
            elif value is original_relationships:
                setattr(module, name, relationship_fragments)

    assert fragments.FRAGMENTS is updated
    assert fragments.BY_FRAGMENT_ID is updated_by_id
    assert filtered.all_relationship_fragments is relationship_fragments
    candidates_after = filtered.candidate_fragments(subgraph)
    candidate_changed = _assert_description_only(candidates_before, candidates_after)
    assert candidate_changed == changed
    assert all(
        fragment is updated_by_id[fragment.fragment_id]
        for fragment in candidates_after
        if fragment.variant in _PEER_VARIANTS
    )
    return {
        "variant": "peer_wording",
        "mutation": "Remove only the second wording-example sentence from both peer fragment descriptions.",
        "changed_description_counts": changed,
        "fragment_count": len(updated),
        "candidate_count_checked": len(candidates_after),
        "description_only_assertion": True,
        "candidate_generator_assertion": True,
    }
