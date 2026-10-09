"""Reader-safe projection and shared rendering of retrieval outcomes."""

import html
import re
from datetime import datetime

from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.schemas.retrieval import (
    ArticleGroup,
    EvidenceAssemblyFailure,
    RetrievalAnswer,
)
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
    groups = ()
    relevance_order = ()
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
        relevance_order = tuple(note.source_article_id for note in result.source_notes)
        if assessment.reading_order in {"publication_asc", "publication_desc"}:
            articles = tuple(
                sorted(
                    articles,
                    key=lambda article: _publication_key(
                        article.citation.published_date,
                        assessment.reading_order == "publication_desc",
                    ),
                )
            )
        organized: list[ArticleGroup] = []
        for group in result.groups:
            order = group.order
            if group.kind == "timeline" and assessment.reading_order in {
                "publication_asc",
                "publication_desc",
            }:
                order = assessment.reading_order
            members = group.members
            if order in {"publication_asc", "publication_desc"}:
                members = tuple(
                    sorted(
                        members,
                        key=lambda member: _publication_key(
                            citations[member.source_article_id].published_date,
                            order == "publication_desc",
                        ),
                    )
                )
            organized.append(
                group.model_copy(update={"order": order, "members": members})
            )
        groups = tuple(organized)
        if assessment.reading_order in {"event_asc", "event_desc"}:
            timeline = next(
                (group for group in groups if group.order == assessment.reading_order),
                None,
            )
            if timeline:
                event_order = {
                    identity: index
                    for index, identity in enumerate(
                        dict.fromkeys(
                            member.source_article_id for member in timeline.members
                        )
                    )
                }
                articles = tuple(
                    sorted(
                        articles,
                        key=lambda article: event_order.get(
                            article.citation.source_article_id, len(event_order)
                        ),
                    )
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
        groups=groups,
        relevance_order=relevance_order,
        partial=bool(execution.failed_branches),
    )


def _publication_key(value: str | None, newest: bool) -> tuple[bool, int]:
    try:
        ordinal = datetime.fromisoformat(value or "").date().toordinal()
    except ValueError:
        return True, 0
    return False, -ordinal if newest else ordinal


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
        for group in guide.groups:
            for member in group.members:
                if member.source_article_id != citation.source_article_id:
                    continue
                direction = f"{group.label}: {member.reading_direction}"
                if group.kind == "timeline":
                    direction += (
                        " Reported event order; publication dates are shown separately."
                        if group.order in {"event_asc", "event_desc"}
                        else " Publication order; publication dates do not establish event dates."
                    )
                if member.reported_event_date:
                    direction += f" Reported event date: {member.reported_event_date}."
                paragraphs.append(f"   - {_escape_markdown_text(direction)}")
    if guide.status == "empty":
        paragraphs.append("No relevant articles were selected from this search.")
    return "\n\n".join(paragraphs)
