"""The resolved conditions observed when a browser Chat Session begins."""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from knowledge_map.schemas.evidence import EvidenceContextLimits
from knowledge_map.schemas.fusion import FusionConfig


@dataclass(frozen=True)
class ChatSessionSettings:
    code_revision: str | None
    worktree_dirty: bool | None
    model_deployments: dict[str, dict[str, object]]
    embedding_settings: dict[str, str]
    prompt_hashes: dict[str, str]
    fusion_settings: FusionConfig
    evidence_limits: EvidenceContextLimits
    coverage_observed_at: str
    retrieval_settings: dict[str, object] = field(default_factory=dict)


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
        revision = os.environ.get("BUILD_REVISION")
        return (revision if revision and revision != "unknown" else None), None
    return revision, bool(status)
