from collections import Counter
from typing import Any

from knowledge_map.jev.filtered_fragments import filter_attachment_rules
from knowledge_map.jev.fragment_selector import SELECTION_FIELDS

THRESHOLD = 0.52


def _expand(fragments: tuple[Any, ...], scores: dict[str, float]) -> dict[str, Any]:
    selected = [
        fragment
        for fragment in fragments
        if scores[fragment.fragment_id] >= THRESHOLD
        and fragment.competition_group is None
    ]
    groups = {
        fragment.competition_group
        for fragment in fragments
        if fragment.competition_group is not None
    }
    for group in groups:
        winner = max(
            (fragment for fragment in fragments if fragment.competition_group == group),
            key=lambda fragment: scores[fragment.fragment_id],
        )
        if scores[winner.fragment_id] >= THRESHOLD:
            selected.append(winner)

    counts: dict[str, Counter[str]] = {field: Counter() for field in SELECTION_FIELDS}
    for fragment in selected:
        for field, ids in fragment.implications.items():
            incoming = Counter(ids)
            for piece_id, count in incoming.items():
                counts[field][piece_id] = max(counts[field][piece_id], count)
    selected_ids = sorted(fragment.fragment_id for fragment in selected)
    return {
        "threshold": THRESHOLD,
        "selected_fragment_ids": selected_ids,
        "selection": {
            field: [
                piece_id
                for piece_id, count in sorted(counts[field].items())
                for _ in range(count)
            ]
            for field in SELECTION_FIELDS
        },
        "filter_attachment_rules": filter_attachment_rules(fragments, selected_ids),
    }
