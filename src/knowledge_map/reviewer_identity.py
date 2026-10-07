"""The local reviewer's identity protocol, shared with its launcher."""

from pathlib import Path


def reviewer_identity(
    mode: str, checkout: Path, reports_dir: Path, samples_dir: Path
) -> dict[str, str]:
    return {
        "service": "ca-map-evaluation-reviewer-v1",
        "mode": mode,
        "checkout": str(checkout.resolve()),
        "reports_dir": str(reports_dir.resolve()),
        "samples_dir": str(samples_dir.resolve()),
    }
