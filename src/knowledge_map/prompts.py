"""Load authored prompt text from explicitly pinned package resources."""

import re
from importlib.resources import files


def load_prompt(name: str, *, version: int) -> str:
    """Read an immutable UTF-8 prompt version without changing its whitespace."""
    if not re.fullmatch(r"[a-z0-9-]+(?:/[a-z0-9-]+)*", name):
        raise ValueError("prompt names must be slash-separated lowercase identifiers")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("prompt versions must be positive integers")
    return (
        files("knowledge_map")
        .joinpath("resources", "prompts", name, f"v{version}.txt")
        .read_text(encoding="utf-8")
    )
