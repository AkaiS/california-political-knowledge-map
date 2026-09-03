"""The Model Deployment an evaluated task runs against when none is named.

Every task under `tasks/` takes the same `str | ModelDeployment` argument
from the registry and defaults to the same local deployment read from
`.env`.  One definition here rather than one per task keeps "the model this
task runs in production" from meaning five slightly different things, the
way `scoring.f1` keeps one meaning for the score a report names `..._f1`.
"""

from __future__ import annotations

from knowledge_map.schemas import DeploymentKind, ModelDeployment
from knowledge_map.utils.models import (
    DEFAULT_LOCAL_CHAT_MODEL,
    resolve_local_chat_model,
)

FALLBACK_MODEL = DEFAULT_LOCAL_CHAT_MODEL


def default_model() -> str:
    """The model the Story Pipeline runs in production, per `.env`.

    Supplies the default a run records when `--model` is not given.  Called
    at import, so it loads `.env` itself.
    """

    return resolve_local_chat_model(FALLBACK_MODEL)


def as_deployment(model: str | ModelDeployment) -> ModelDeployment:
    """Turn a legacy model argument into an explicit local deployment."""

    if isinstance(model, ModelDeployment):
        return model
    return ModelDeployment(kind=DeploymentKind.LOCAL, model=model)
