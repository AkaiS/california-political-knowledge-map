"""Decide whether commits change the sources the production image is built from."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DOCKERIGNORE = Path(__file__).parents[1] / ".dockerignore"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


class ImageInputsError(Exception):
    """The comparison could not be made."""


def image_inputs(dockerignore: Path = DOCKERIGNORE) -> list[str]:
    # The build context is an allowlist, so its re-included paths are the only
    # files that can change the image. Later exclusions only narrow those paths.
    patterns = [
        line.strip()
        for line in dockerignore.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not patterns or patterns[0] != "*":
        raise ImageInputsError(".dockerignore must start by excluding everything.")
    paths = []
    for pattern in patterns[1:]:
        if pattern.startswith("!"):
            path = pattern[1:].removesuffix("/**").rstrip("/")
            if path not in paths:
                paths.append(path)
    return paths


def image_changed(base: str, head: str, environment=None) -> bool:
    if not SHA_PATTERN.fullmatch(base) or not SHA_PATTERN.fullmatch(head):
        raise ImageInputsError("Image comparison requires two commit SHAs.")
    try:
        result = subprocess.run(
            ["git", "diff", "--quiet", base, head, "--", *image_inputs()],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise ImageInputsError("Cannot compare image sources.") from None
    if result.returncode not in (0, 1):
        raise ImageInputsError("Cannot compare image sources.")
    return result.returncode == 1


def main(base: str, head: str) -> int:
    # A push without a previous main commit has nothing to compare against.
    changed = set(base) == {"0"} or image_changed(base, head)
    print(f"changed={'true' if changed else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
