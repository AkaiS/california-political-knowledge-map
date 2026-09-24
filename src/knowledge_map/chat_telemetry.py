"""The resolved conditions observed when a browser Chat Session begins."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from knowledge_map.schemas.evidence import EvidenceContextLimits
from knowledge_map.schemas.fusion import FusionConfig


@dataclass(frozen=True)
class ChatSessionSettings:
    code_revision: str | None
    worktree_dirty: bool | None
    model_deployments: dict[str, dict[str, object]]
    prompt_hashes: dict[str, str]
    fusion_settings: FusionConfig
    evidence_limits: EvidenceContextLimits
    coverage_observed_at: str


def code_state() -> tuple[str | None, bool | None]:
    """Observe the application checkout, even when launched from another directory."""
    root = Path(__file__).resolve().parents[2]
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None, None
    return revision, bool(status)
