"""Browser presentation of completed retrieval outcomes."""

import html
import re

from knowledge_map.schemas.retrieval import EvidenceAssemblyFailure, RetrievalAnswer


def search_details(
    result: RetrievalAnswer | EvidenceAssemblyFailure,
) -> dict[str, object]:
    """Select inspectable provenance without serializing candidate grounding."""
    execution = (
        result.evidence.execution
        if isinstance(result, RetrievalAnswer)
        else result.execution
    )
    branches: list[dict[str, object]] = []
    for outcome in execution.outcomes:
        branch: dict[str, object] = {
            "branch": outcome.branch.value,
            "status": outcome.status,
        }
        if outcome.status == "succeeded":
            branch["candidates"] = [
                candidate.model_dump(
                    mode="json",
                    include={"chunk_id", "source_article_id", "ranking", "routes"},
                )
                for candidate in outcome.candidates
            ]
        elif outcome.status == "skipped":
            branch["reason"] = outcome.reason
        branches.append(branch)
    return {
        "outcome": "retrieval_answer"
        if isinstance(result, RetrievalAnswer)
        else "assembly_failed",
        "branches": branches,
        "coverage": result.evidence.coverage.model_dump(mode="json")
        if isinstance(result, RetrievalAnswer)
        else None,
    }


def _escape_markdown_text(text: str) -> str:
    return re.sub(r"([\\`*_\[\]{}])", r"\\\1", html.escape(text, quote=False))


def render_answer(result: RetrievalAnswer | EvidenceAssemblyFailure) -> str:
    if isinstance(result, EvidenceAssemblyFailure):
        disclosures = list(result.failure_disclosures)
        assessment = result.execution.request.rewrite.assessment
        if assessment.status == "deferred" and assessment.explanation:
            disclosures.append(assessment.explanation)
        return "\n\n".join(disclosures)
    paragraphs = [result.introduction] if result.introduction else []
    execution = result.evidence.execution
    assessment = execution.request.rewrite.assessment
    for disclosure in (
        *execution.failure_disclosures,
        execution.structural_empty_disclosure,
        assessment.explanation if assessment.status == "deferred" else None,
    ):
        if disclosure and disclosure not in (result.introduction or ""):
            paragraphs.append(disclosure)
    source_numbers = {}
    for number, source in enumerate(result.evidence.sources, start=1):
        citation = source.citation
        source_numbers[citation.source_article_id] = number
        paragraphs.append(
            f"{number}. [{_escape_markdown_text(citation.title)}](<{citation.url}>)"
        )
        paragraphs.extend(
            _escape_markdown_text(note.note)
            for note in result.source_notes
            if note.source_article_id == citation.source_article_id
        )
        for passage in source.passages:
            paragraphs.append(
                "\n".join(
                    f"> {_escape_markdown_text(line)}"
                    for line in passage.text.splitlines()
                )
            )
    for disagreement in result.disagreements:
        numbers = ", ".join(
            str(source_numbers[source_id])
            for source_id in disagreement.source_article_ids
        )
        paragraphs.append(
            f"Sources {numbers}: {_escape_markdown_text(disagreement.description)}"
        )
    if not result.evidence.sources:
        paragraphs.append("No verified passages were selected.")
    return "\n\n".join(paragraphs)
