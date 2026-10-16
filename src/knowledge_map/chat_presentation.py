"""Reader-safe projection and shared rendering of retrieval outcomes."""

import html
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import HttpUrl, ValidationError

from knowledge_map.adapters import sqlite_db
from knowledge_map.schemas.query_preparation import QuestionAssessment
from knowledge_map.schemas.retrieval import (
    ArticleGroup,
    CoverageDescription,
    EvidenceAssemblyFailure,
    RetrievalAnswer,
    SourceArticleEvidence,
)
from knowledge_map.schemas.source_guides import (
    GuideArticle,
    GuideCollection,
    GuideDisclosure,
    GuideSearchDetails,
    SourceGuide,
)


def guide_collections(coverage: CoverageDescription) -> tuple[GuideCollection, ...]:
    """Keep saved search scope and question-entry coverage on the same projection."""
    return tuple(
        GuideCollection.model_validate(
            entry.model_dump(
                include={"name", "date_basis", "earliest_date", "latest_date"}
            )
        )
        for entry in coverage.entries
    )


def _assessment_guide(question: str, assessment: QuestionAssessment) -> SourceGuide:
    if assessment.status not in {"declined", "needs_edit"}:
        raise ValueError("only a Declined or needs-edit assessment ends a Chat Session")
    assert assessment.explanation is not None
    return SourceGuide(
        question=question,
        status=assessment.status,
        assessment=assessment,
        message=assessment.explanation,
        disclosures=(
            GuideDisclosure(kind=assessment.status, message=assessment.explanation),
        ),
    )


def deferred_disclosures(
    assessment: QuestionAssessment | None,
) -> tuple[GuideDisclosure, ...]:
    """Retain the same Deferred coverage explanation after success or failure."""
    if assessment is None or assessment.status != "deferred":
        return ()
    return (
        GuideDisclosure(
            kind="deferred",
            message=f"{assessment.explanation}\n\n{assessment.recoverable_portion}",
        ),
    )


type ChatSessionOutcome = RetrievalAnswer | EvidenceAssemblyFailure | QuestionAssessment


def project_source_guide(
    outcome: ChatSessionOutcome,
    *,
    question: str,
    story_db_path: str | Path,
) -> SourceGuide:
    """Decide the terminal Source Guide a reader sees for a Chat Session outcome.

    Publications and original-section highlights come from the named story
    document store, so every caller renders the same links.
    """
    if isinstance(outcome, QuestionAssessment):
        return _assessment_guide(question, outcome)
    return _retrieval_guide(outcome, question, str(story_db_path))


def _retrieval_guide(
    result: RetrievalAnswer | EvidenceAssemblyFailure,
    question: str,
    story_db_path: str,
) -> SourceGuide:
    execution = (
        result.evidence.execution
        if isinstance(result, RetrievalAnswer)
        else result.execution
    )
    assessment = execution.request.rewrite.assessment
    disclosures: list[GuideDisclosure] = []
    articles: tuple[GuideArticle, ...] = ()
    groups = ()
    relevance_order = ()
    if isinstance(result, RetrievalAnswer):
        citations = {
            source.citation.source_article_id: source.citation.model_copy(
                update={"url": _ordinary_url(source.citation.url)}
            )
            for source in result.evidence.sources
        }
        sources = {
            source.citation.source_article_id: source
            for source in result.evidence.sources
        }
        articles = tuple(
            GuideArticle(
                citation=citations[note.source_article_id],
                reading_direction=note.note,
                publication=sqlite_db.get_article_publication(
                    note.source_article_id, story_db_path
                ),
                section_links=_section_links(
                    sources[note.source_article_id], story_db_path
                ),
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
        disclosures.extend(
            GuideDisclosure(
                kind="unmatched_request",
                request_portion=gap.request_portion,
                message=gap.explanation,
            )
            for gap in result.unmatched_requests
        )
    if isinstance(result, EvidenceAssemblyFailure):
        disclosures.append(
            GuideDisclosure(
                kind="assembly_failed",
                message="Retrieved material could not be prepared for relevance review. Choose Retry to search again.",
            )
        )
    elif len(execution.failed_branches) == len(execution.expected_branches):
        disclosures.append(
            GuideDisclosure(
                kind="retrieval_failed",
                message="The search failed before articles could be assessed. Choose Retry to search again.",
            )
        )
    elif not articles:
        disclosures.append(
            GuideDisclosure(
                kind="irrelevant_candidates"
                if result.evidence.sources
                else "no_matches",
                message=(
                    "Retrieved articles were assessed, but none supported a reading direction for this question."
                    if result.evidence.sources
                    else "No articles were available to assess within this search's limits."
                )
                + " This does not establish that matching reporting does not exist.",
            )
        )
    if execution.failed_branches and len(execution.failed_branches) < len(
        execution.expected_branches
    ):
        disclosures.append(
            GuideDisclosure(
                kind="partial_search",
                message="Part of this search failed. Available reading is retained, but this search is incomplete.",
            )
        )
    disclosures.extend(deferred_disclosures(assessment))
    return SourceGuide(
        question=question,
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
        message="\n\n".join(disclosure.message for disclosure in disclosures) or None,
        disclosures=tuple(disclosures),
        articles=articles,
        groups=groups,
        relevance_order=relevance_order,
        partial=bool(execution.failed_branches),
        search_details=GuideSearchDetails(
            collections=guide_collections(result.evidence.coverage),
            completion="failed"
            if len(execution.failed_branches) == len(execution.expected_branches)
            else "partial"
            if execution.failed_branches
            else "completed",
            selection_limited=bool(result.evidence.context.omitted_passages),
            included_articles=len(articles),
        )
        if isinstance(result, RetrievalAnswer)
        else None,
    )


def _section_links(source: SourceArticleEvidence, db_path: str) -> tuple[HttpUrl, ...]:
    try:
        original_url = HttpUrl(source.citation.source_article_id)
    except ValidationError:
        return ()
    if urlsplit(str(original_url))._replace(fragment="") != urlsplit(
        str(source.citation.url)
    )._replace(fragment=""):
        return ()
    original = sqlite_db.get_story_content(source.citation.source_article_id, db_path)
    if not original:
        return ()
    original = " ".join(original.split())
    links = []
    for passage in source.passages:
        text = " ".join(passage.text.split())
        if not text or text not in original or not _unique_match(original, text):
            continue
        start = original.index(text)
        if text[0].isalnum() and start and original[start - 1].isalnum():
            continue
        target = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
        if len(target) > 160:
            target = target[:160].rpartition(" ")[0]
        if not target:
            continue
        end = start + len(target)
        if target[-1].isalnum() and end < len(original) and original[end].isalnum():
            continue
        directive = _fragment_term(target)
        if not _unique_match(original, target):
            suffix = text[len(target) :].strip()
            if len(suffix) > 80:
                suffix = suffix[:80].rpartition(" ")[0]
            if not suffix or not _unique_match(original, f"{target} {suffix}"):
                continue
            suffix_end = start + len(target) + 1 + len(suffix)
            if (
                suffix[-1].isalnum()
                and suffix_end < len(original)
                and original[suffix_end].isalnum()
            ):
                continue
            directive += ",-" + _fragment_term(suffix)
        url = urlsplit(str(_ordinary_url(source.citation.url)))
        try:
            links.append(
                HttpUrl(
                    urlunsplit(
                        url._replace(fragment=url.fragment + ":~:text=" + directive)
                    )
                )
            )
        except ValidationError:
            continue
    return tuple(dict.fromkeys(links))


def _unique_match(original: str, text: str) -> bool:
    original_key = _fragment_comparison_key(original)
    text_key = _fragment_comparison_key(text)
    if original_key is None or text_key is None:
        return False
    return len(re.findall(f"(?={re.escape(text_key)})", original_key)) == 1


def _fragment_comparison_key(text: str) -> str | None:
    # Browser matching ignores accents. Unmapped letters need ordinary fallback
    # rather than a second implementation of Unicode primary collation.
    key = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(character)
    )
    if any(character.isalnum() and not character.isascii() for character in key):
        return None
    return key


def _ordinary_url(url: HttpUrl) -> HttpUrl:
    parts = urlsplit(str(url))
    return HttpUrl(
        urlunsplit(parts._replace(fragment=parts.fragment.split(":~:", 1)[0]))
    )


def _fragment_term(text: str) -> str:
    return quote(text, safe="").replace("-", "%2D")


def _publication_key(value: str | None, newest: bool) -> tuple[bool, int]:
    try:
        ordinal = datetime.fromisoformat(value or "").date().toordinal()
    except ValueError:
        return True, 0
    return False, -ordinal if newest else ordinal


def guide_publication_orders(guide: SourceGuide) -> dict[str, tuple[str, ...]]:
    """Order every saved article by its stated day, retaining relevance on ties."""
    relevance = {
        identity: index for index, identity in enumerate(guide.relevance_order)
    }
    articles = sorted(
        guide.articles,
        key=lambda article: relevance.get(
            article.citation.source_article_id, len(relevance)
        ),
    )
    return {
        order: tuple(
            article.citation.source_article_id
            for article in sorted(
                articles,
                key=lambda article: _publication_key(
                    article.citation.published_date, order == "publication_desc"
                ),
            )
        )
        for order in ("publication_asc", "publication_desc")
    }


def _escape_markdown_text(text: str) -> str:
    return re.sub(r"([\\`*_\[\]{}])", r"\\\1", html.escape(text, quote=False))


def render_source_guide(guide: SourceGuide) -> str:
    """Evaluation consumers see the same reading selection as the application."""
    paragraphs = [_escape_markdown_text(guide.question)]
    if guide.disclosures:
        for disclosure in guide.disclosures:
            text = disclosure.message
            if disclosure.kind == "unmatched_request":
                text = f"Unmatched part of your question: {disclosure.request_portion}. {text}"
            if disclosure.kind == "deferred":
                text = f"Deferred coverage: {text}"
            paragraphs.append(_escape_markdown_text(text))
    elif guide.message:
        paragraphs.append(_escape_markdown_text(guide.message))
    for number, article in enumerate(guide.articles, start=1):
        citation = article.citation
        paragraphs.append(
            f"{number}. [{_escape_markdown_text(citation.title)}](<{citation.url}>)"
        )
        if article.publication:
            paragraphs.append(_escape_markdown_text(article.publication))
        if citation.published_date:
            paragraphs.append(_escape_markdown_text(citation.published_date))
        paragraphs.append(_escape_markdown_text(article.reading_direction))
        for index, url in enumerate(article.section_links, start=1):
            paragraphs.append(f"   - [Relevant highlight {index}](<{url}>)")
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
