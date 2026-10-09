"""Run the existing chat evaluation task against fixed fictional retrieval IO.

Run with uv run --no-sync python work/projects/source-guides/validation/run_controlled.py.
Only the Chat Agent uses the local deployment; retrieval is a controlled fixture.
"""

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import patch

from knowledge_map.chat_startup import ChatDependencies
from knowledge_map.chat_telemetry import ChatSessionSettings, code_state
from knowledge_map.core.chat import CHAT_INSTRUCTIONS, QUESTION_POLICY, get_chat_agent
from knowledge_map.core.retrieval import RetrievalCoordinator
from knowledge_map.evaluation import load_data_set, run_data_set, write_report
from knowledge_map.evaluation.data_set import LabelQuality
from knowledge_map.evaluation.tasks import chat
from knowledge_map.schemas import DeploymentKind, ModelDeployment
from knowledge_map.schemas.evidence import EvidenceContextLimits
from knowledge_map.schemas.fusion import FusionConfig
from knowledge_map.schemas.model_deployment import ModelRequestSettings
from knowledge_map.schemas.retrieval import (
    BranchCandidate,
    BranchRanking,
    CoverageAvailability,
    CoverageDescription,
    CoverageEntry,
    GraphNodeReference,
    GroundingEvidence,
    RetrievalBranch,
    RetrievalRoute,
    SourceArticleCitation,
    SuccessfulBranch,
)

ARTICLES = (
    (
        "hearing",
        "Housing grants hearing",
        "2025-03-01",
        (
            "California AB 1 would expand affordable housing grants. The committee met on March 2, 2023. "
            "A committee hearing included a supporters section in which the Tenants Association "
            "argued that the grants would reduce rent pressure, and a detractors section in which "
            "the Municipal Budget Council argued that the matching costs would strain city budgets. "
            "The Tenants Association said the committee received its cost memo, while "
            "the Municipal Budget Council said it had not received the same memo."
        ),
    ),
    (
        "proposal",
        "Housing proposal introduced",
        "2024-01-15",
        (
            "California AB 1 was introduced in January 2022 with housing construction "
            "grant provisions. A section on eligibility explains which local governments could "
            "apply. Another section describes the scope of the initial proposal and the public hearing schedule."
        ),
    ),
    (
        "fishing",
        "Salmon season reporting",
        "2024-09-01",
        (
            "California salmon fishing seasons were discussed "
            "at a fishery commission meeting. The story concerns river conditions and fishing permits."
        ),
    ),
)
COVERAGE = CoverageDescription(
    entries=(
        CoverageEntry(
            collection_id="calmatters",
            name="Controlled Reporting",
            kind="publication",
            description="California political reporting on legislation, housing, education, and fisheries.",
            availability=CoverageAvailability(available_count=3),
            date_basis="publication_date",
            earliest_date="2024-01-15",
            latest_date="2025-03-01",
        ),
    )
)


class ControlledBranch:
    def __init__(self, branch):
        self.branch = branch

    async def retrieve(self, request, *, deadline, keywords=None, usage=None):
        if self.branch != RetrievalBranch.FULL_TEXT:
            return SuccessfulBranch(branch=self.branch, candidates=())
        return SuccessfulBranch(
            branch=self.branch,
            candidates=tuple(
                BranchCandidate(
                    chunk_id=slug,
                    source_article_id=f"https://example.org/{slug}",
                    ranking=BranchRanking(branch=self.branch, rank=rank, score=None),
                    routes=(
                        RetrievalRoute(
                            kind="chunk_text",
                            matched_field="text",
                            entry_node=GraphNodeReference(id=slug, label="Chunk"),
                        ),
                    ),
                )
                for rank, (slug, *_rest) in enumerate(ARTICLES, 1)
            ),
        )


async def grounding(candidate):
    slug, title, date, text = next(
        row for row in ARTICLES if row[0] == candidate.chunk_id
    )
    return GroundingEvidence(
        chunk_id=slug,
        text=text,
        citation=SourceArticleCitation(
            source_article_id=candidate.source_article_id,
            title=title,
            url=f"https://example.org/{slug}",
            published_date=date,
        ),
    )


@asynccontextmanager
async def controlled_dependencies(*, chat_deployment, capabilities):
    agent = get_chat_agent(
        chat_deployment, cache_model=False, capabilities=capabilities
    )
    revision, dirty = code_state()
    try:
        yield ChatDependencies(
            None,
            agent,
            RetrievalCoordinator(
                full_text=ControlledBranch(RetrievalBranch.FULL_TEXT),
                dense=ControlledBranch(RetrievalBranch.DENSE),
                structural=ControlledBranch(RetrievalBranch.STRUCTURAL),
                load_grounding=grounding,
                structural_reporting=True,
            ),
            COVERAGE,
            None,
            chat_deployment,
            ChatSessionSettings(
                code_revision=revision,
                worktree_dirty=dirty,
                model_deployments={
                    "chat_agent": chat_deployment.model_dump(mode="json")
                },
                embedding_settings={"fixture": "no embedding calls"},
                prompt_hashes={
                    key: "sha256:"
                    + hashlib.sha256(
                        (value if key == "question_policy" else value.strip()).encode()
                    ).hexdigest()
                    for key, value in {
                        "chat_agent": CHAT_INSTRUCTIONS,
                        "question_policy": QUESTION_POLICY,
                    }.items()
                },
                fusion_settings=FusionConfig(),
                evidence_limits=EvidenceContextLimits(),
                coverage_observed_at=datetime.now(UTC).isoformat(),
                retrieval_settings={
                    "fixture": "SG01/SG07 fixed fictional reporting; no database or Jev model calls"
                },
            ),
        )
    finally:
        await agent.model.client.close()


def main():
    path = "evals/unlabeled/source-guides.yaml"
    data = load_data_set(
        path,
        input_type=chat.ChatInput,
        output_type=chat.ChatOutput,
        metadata_type=chat.ChatMetadata,
    )
    deployment = ModelDeployment(
        kind=DeploymentKind.LOCAL,
        model="gemma4:26b",
        request_settings=ModelRequestSettings(
            timeout=120, max_tokens=1600, max_attempts=1
        ),
    )
    with patch.object(chat, "chat_dependencies", controlled_dependencies):
        report = run_data_set(
            data,
            task=chat.build_task(deployment, data),
            evaluators=(),
            case_lifecycle=chat.ChatCaseLifecycle,
            experiment_metadata={
                "retrieval": "fixed fictional SG01/SG07 fixture",
                "prompt": "chat/instructions/v10; chat/question-policy/v2",
            },
        )
    saved = write_report(
        report,
        task="chat",
        deployment=deployment,
        data_set_path=path,
        label_quality=LabelQuality.UNLABELED,
    )
    print(saved)
    for case in report.cases:
        print(
            case.name,
            case.output.guide.model_dump(mode="json")
            if case.output.guide
            else case.output.failure,
        )


if __name__ == "__main__":
    main()
