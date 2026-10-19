"""Saved Evaluation Reports pinned for comparing a scorecard's markdown in full.

A run records metadata from its environment (time, commit, worktree state)
and measures how long each case took; paths differ on every run too.  Tests
pin the recorded metadata before building a ``Scorecard`` and replace what
still varies by name before comparing its markdown.
"""

from __future__ import annotations

import json
import re

# A case's task duration is measured, so its quantile rows differ on every run.
DURATION_VALUE = re.compile(r"(\| task_duration_p\d+ \| )[^|]+")


def pinned(path, metadata=None, **fields):
    """Save ``path`` again with its environment-recorded fields pinned.

    ``metadata`` overrides keys of the recorded ``experiment_metadata``.
    """

    document = json.loads(path.read_text())
    document.update(
        {
            "commit": "1234567",
            "dirty": False,
            "trace_url": None,
            "ran_at": "2026-10-02T12:00:00+00:00",
            "data_set_sha256": "ab" * 32,
            "experiment_metadata": {
                **document["experiment_metadata"],
                "prompts": {document["task"]: "cd" * 32},
                "selection": {"scope": "full"},
                **(metadata or {}),
            },
            **fields,
        }
    )
    path.write_text(json.dumps(document))
    return path


def markdown(card, **names):
    """``card``'s markdown with each named report's path replaced by its name.

    Each measured task duration is replaced by ``<duration>``.
    """

    text = card.to_markdown()
    for name, path in names.items():
        text = text.replace(str(path.resolve()), f"<{name}>")
    return DURATION_VALUE.sub(r"\1<duration> ", text)
