"""Reader-safe projection and shared rendering of retrieval outcomes."""

import html
import re
from datetime import datetime

from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.schemas.retrieval import EvidenceAssemblyFailure, RetrievalAnswer
from knowledge_map.schemas.source_guides import GuideArticle, SourceGuide


def assessment_guide(question: str, assessment: QuestionAssessment) -> SourceGuide:
    """Present a terminal assessment consistently across guide consumers."""
    assert assessment.status == "declined" or assessment.status == "needs_edit"
    return SourceGuide(
        question=question,
        status=assessment.status,
        assessment=assessment,
        message=assessment.explanation,
    )


def source_guide(result: RetrievalAnswer | EvidenceAssemblyFailure) -> SourceGuide:
    execution = (
        result.evidence.execution
        if isinstance(result, RetrievalAnswer)
        else result.execution
    )
    assessment = execution.request.rewrite.assessment
    disclosures = (
        list(result.failure_disclosures)
        if isinstance(result, EvidenceAssemblyFailure)
        else []
    )
    articles: tuple[GuideArticle, ...] = ()
    if isinstance(result, RetrievalAnswer):
        citations = {
            source.citation.source_article_id: source.citation
            for source in result.evidence.sources
        }
        articles = tuple(
            GuideArticle(
                citation=citations[note.source_article_id], reading_direction=note.note
            )
            for note in result.source_notes
        )
        if assessment.reading_order != "relevance":

            def publication_date(article: GuideArticle) -> int | None:
                try:
                    return (
                        datetime.fromisoformat(article.citation.published_date or "")
                        .date()
                        .toordinal()
                    )
                except ValueError:
                    return None

            dated = [
                article for article in articles if publication_date(article) is not None
            ]
            undated = [
                article for article in articles if publication_date(article) is None
            ]
            articles = tuple(
                sorted(
                    dated,
                    key=lambda article: publication_date(article) or 0,
                    reverse=assessment.reading_order == "publication_desc",
                )
                + undated
            )
        if result.introduction:
            disclosures.append(result.introduction)
    for disclosure in (
        *execution.failure_disclosures,
        execution.structural_empty_disclosure,
        assessment.explanation if assessment.status == "deferred" else None,
        assessment.recoverable_portion if assessment.status == "deferred" else None,
    ):
        if disclosure and not any(disclosure in existing for existing in disclosures):
            disclosures.append(disclosure)
    return SourceGuide(
        question=execution.request.rewrite.question,
        status=(
            "assembly_failed"
            if isinstance(result, EvidenceAssemblyFailure)
            else "retrieval_failed"
            if len(execution.failed_branches) == len(execution.expected_branches)
            else "completed"
            if articles
            else "empty"
        ),
        assessment=assessment,
        message="\n\n".join(disclosures) or None,
        articles=articles,
        partial=bool(execution.failed_branches),
    )


def _escape_markdown_text(text: str) -> str:
    return re.sub(r"([\\`*_\[\]{}])", r"\\\1", html.escape(text, quote=False))


def render_answer(result: RetrievalAnswer | EvidenceAssemblyFailure) -> str:
    """Evaluation consumers see the same reading selection as the application."""
    guide = source_guide(result)
    paragraphs = [_escape_markdown_text(guide.question)]
    if guide.message:
        paragraphs.append(_escape_markdown_text(guide.message))
    for number, article in enumerate(guide.articles, start=1):
        citation = article.citation
        paragraphs.append(
            f"{number}. [{_escape_markdown_text(citation.title)}](<{citation.url}>)"
        )
        if citation.published_date:
            paragraphs.append(_escape_markdown_text(citation.published_date))
        paragraphs.append(_escape_markdown_text(article.reading_direction))
    if guide.status == "empty":
        paragraphs.append("No relevant articles were selected from this search.")
    return "\n\n".join(paragraphs)
