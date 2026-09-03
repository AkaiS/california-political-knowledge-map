import logging
from typing import List, Optional, Protocol

from knowledge_map.core.bill_sessions import resolve_bill_sessions
from knowledge_map.core.legislative_events import resolve_legislative_event_dates
from knowledge_map.core.topic_assignment import extracted_measures, supported_assignments
from knowledge_map.schemas import (
    AdherenceReport,
    ArticleChunk,
    StoryStatus,
    BillSessionResolutions,
    CoreferenceResolutionRun,
    ExtractionResult,
    LegislativeEventDates,
    Node,
    PipelineResult,
    SourceArticle,
    TopicAssignment,
)
from knowledge_map.utils.chunking import chunk_article

logger = logging.getLogger(__name__)

class DatabaseAdapter(Protocol):
    def ingest_article(self, article: SourceArticle) -> None:
        ...

    def ingest_chunk(
        self,
        article: SourceArticle,
        chunk: ArticleChunk,
        embedding: List[float]
    ) -> None:
        ...

    def ingest_chunk_extraction(
        self,
        chunk_id: str,
        extraction: ExtractionResult,
        bill_sessions: BillSessionResolutions | None = None,
        event_dates: LegislativeEventDates | None = None,
    ) -> None:
        ...

    def ingest_article_topics(
        self,
        article: SourceArticle,
        policy_areas: List[str],
        assignments: List[TopicAssignment] | None = None,
        bill_sessions: BillSessionResolutions | None = None,
    ) -> None:
        """Write the Policy Areas a Source Article discusses and its assignments.

        Named for the level it works at: these edges are decided once per
        article, unlike the per-chunk write above.
        """
        ...

    def health_check(self) -> bool:
        ...

class EmbeddingAdapter(Protocol):
    def process_chunks(self, chunks: List[ArticleChunk]) -> List[List[float]]:
        ...

    def health_check(self) -> bool:
        ...

class CoreferenceAdapter(Protocol):
    def resolve(self, content: str) -> CoreferenceResolutionRun:
        ...

    def health_check(self) -> bool:
        ...

class EntityExtractionAdapter(Protocol):
    def extract(self, chunk_text: str) -> ExtractionResult:
        ...

    @property
    def adherence_report(self) -> AdherenceReport:
        """Ontology items dropped from model output since the last reset."""
        ...

    def reset_adherence_report(self) -> None:
        ...

    def health_check(self) -> bool:
        ...

class PolicyAreaAdapter(Protocol):
    """The article-level topic judgement, decided once per Source Article.

    One seam for both article-level topic stages: classification over the
    resolved text here, and Topic Assignment beside it once extraction has
    discovered the measures.
    """

    def classify(self, resolved_text: str) -> List[str]:
        """The Policy Areas the article discusses, by canonical name."""
        ...

    def assign(
        self,
        article: SourceArticle,
        policy_areas: List[str],
        measures: List[Node],
    ) -> List[TopicAssignment]:
        """Which of the article's Policy Areas each of its measures is about.

        The article's content is the resolved text, as it is for classification
        beside it: the areas and the measures were both derived from that text,
        so judging them against the raw content would read pronouns where the
        measures are named.

        Measures are named by the surface strings extraction produced, which is
        the only vocabulary an assignment may draw its measures from.
        """
        ...

    def health_check(self) -> bool:
        ...


class DeadLetterQueueAdapter(Protocol):
    def log_failure(
        self,
        url: str,
        title: str,
        original_text: str,
        validation_issues: List[str],
        failure_type: str,
        retry_count: int,
        metadata: dict,
        error_category: str = "coreference",
        resolution_run: CoreferenceResolutionRun | None = None,
    ) -> str:
        ...

class StatusTracker(Protocol):
    def update_status(self, url: str, status: str) -> None:
        ...

from knowledge_map.adapters.coreference import CoreferenceResolutionError
from knowledge_map.adapters.extraction import ExtractionError
from knowledge_map.adapters.policy_areas import (
    PolicyAreaClassificationError,
    TopicAssignmentError,
)
from knowledge_map.core.exceptions import (
    PipelineConnectivityError,
    PipelineException,
    PipelineRateLimitError,
    transport_failures_as_pipeline_errors,
)


#: The Dead Letter Queue category each stage failure is recorded under, so the
#: pipeline keeps one vocabulary of failure across its stages.
_ERROR_CATEGORIES = {
    CoreferenceResolutionError: "coreference",
    ExtractionError: "extraction",
    PolicyAreaClassificationError: "policy_area_classification",
    TopicAssignmentError: "topic_assignment",
}


def _error_category(e: Exception) -> Optional[str]:
    """The category a stage failure is recorded under, or None if it is not one.

    Matched by isinstance rather than exact type, so a stage that narrows its
    failure into a subclass is still recorded rather than raising out of the
    failure handler and displacing the failure it was called to report.
    """

    for error_type, category in _ERROR_CATEGORIES.items():
        if isinstance(e, error_type):
            return category
    return None


class StoryPipeline:
    def __init__(
        self,
        db_adapter: DatabaseAdapter,
        embedding_adapter: EmbeddingAdapter,
        coreference_adapter: CoreferenceAdapter,
        extraction_adapter: EntityExtractionAdapter,
        policy_area_adapter: PolicyAreaAdapter,
        status_tracker: StatusTracker,
        dlq_adapter: Optional[DeadLetterQueueAdapter] = None,
    ) -> None:
        self.db_adapter = db_adapter
        self.embedding_adapter = embedding_adapter
        self.coreference_adapter = coreference_adapter
        self.extraction_adapter = extraction_adapter
        self.policy_area_adapter = policy_area_adapter
        self.status_tracker = status_tracker
        self.dlq_adapter = dlq_adapter

    def run(self, article: SourceArticle, dry_run: bool = False) -> PipelineResult:
        logger.info(f"Starting pipeline run for article: {article.title or article.url}")
        
        if not dry_run:
            self.status_tracker.update_status(article.url, StoryStatus.PROCESSING)

        try:
            # 1. Resolve coreferences
            logger.info("Resolving coreferences...")
            with transport_failures_as_pipeline_errors("coreference"):
                resolution_run = self.coreference_adapter.resolve(article.content)
            resolved_text = resolution_run.resolved_text
            critic_outcomes = [o for o in resolution_run.outcomes if o.stage == "critic"]
            logger.info(
                f"Coreference resolved: {len(resolution_run.surviving_spans)} span(s) survived, "
                f"{resolution_run.discarded_count} did not "
                f"({len(critic_outcomes)} judged by the Critic, "
                f"{resolution_run.retry_count} correction round(s), "
                f"{resolution_run.discarded_proportion:.1%} discarded)."
            )

            # 2. Policy Area Classification, over the resolved text and
            # before chunking: it is decided once for the article, and
            # nothing earlier needs its result.
            logger.info("Classifying Policy Areas...")
            with transport_failures_as_pipeline_errors("policy_area_classification"):
                policy_areas = self.policy_area_adapter.classify(resolved_text)
            logger.info(f"Article classified into {len(policy_areas)} Policy Area(s).")

            # 3. Chunking
            logger.info("Chunking text...")
            chunks = chunk_article(resolved_text)

            # 4. Embedding
            logger.info("Generating embeddings...")
            with transport_failures_as_pipeline_errors("embedding"):
                embeddings = self.embedding_adapter.process_chunks(chunks)

            # 5. Extraction
            logger.info("Extracting entities...")
            extractions = []
            for idx, chunk in enumerate(chunks):
                logger.info(f"Extracting chunk {idx}...")
                with transport_failures_as_pipeline_errors("extraction"):
                    extraction = self.extraction_adapter.extract(chunk.text)
                extractions.append(extraction)

            bill_sessions = resolve_bill_sessions(article, extractions)
            event_dates = resolve_legislative_event_dates(
                extractions, article.published_date
            )

            # 6. Topic Assignment, the other article-level pass over the
            # extractions: it needs every measure the article names, so it
            # cannot run before extraction has discovered them.  With no areas
            # or no measures there is nothing for it to decide.
            measures = extracted_measures(extractions)
            assignments: List[TopicAssignment] = []
            if policy_areas and measures:
                logger.info("Assigning measures to Policy Areas...")
                # Assignment reads the article as its other two inputs were
                # derived: the areas were classified over the resolved text and
                # the measures were extracted from chunks of it.  Handing it the
                # raw content would ask it to connect measures named by resolved
                # surface strings to a text that still says "the bill".
                resolved_article = article.model_copy(
                    update={"content": resolved_text}
                )
                with transport_failures_as_pipeline_errors("topic_assignment"):
                    assignments = self.policy_area_adapter.assign(
                        resolved_article, policy_areas, measures
                    )
                # Both drops are enforced here rather than in the prompt: the
                # write path matches an assignment's endpoints, so one naming a
                # measure or an area that is not there would write nothing at
                # all instead of saying so.
                assignments = supported_assignments(
                    assignments, measures, policy_areas
                )
            logger.info(f"Assigned {len(assignments)} measure(s) to a Policy Area.")

            # 7. DB Persistence (skip if dry_run)
            if not dry_run:
                logger.info("Ingesting article and chunks into DB...")
                self.db_adapter.ingest_article(article)
                for idx, chunk in enumerate(chunks):
                    chunk_id = f"{article.url}#chunk_{idx}"
                    embedding = embeddings[idx] if idx < len(embeddings) else []
                    self.db_adapter.ingest_chunk(article, chunk, embedding)
                    self.db_adapter.ingest_chunk_extraction(
                        chunk_id, extractions[idx], bill_sessions, event_dates
                    )

                # Both halves of the article-level topic judgement are written
                # together, at the level they were decided.
                self.db_adapter.ingest_article_topics(
                    article, policy_areas, assignments, bill_sessions
                )

                # 8. Update status to COMPLETED
                self.status_tracker.update_status(article.url, StoryStatus.COMPLETED)

            return PipelineResult(
                resolved_text=resolved_text,
                policy_areas=policy_areas,
                chunks=chunks,
                embeddings=embeddings,
                extractions=extractions,
            )
        except Exception as e:
            self._handle_pipeline_failure(e, article, dry_run)
            raise e

    def _safe_update_status(self, url: str, status: StoryStatus) -> None:
        try:
            self.status_tracker.update_status(url, status)
        except Exception as status_err:
            logger.error(f"Failed to update status to {status}: {status_err}")

    def _handle_pipeline_failure(self, e: Exception, article: SourceArticle, dry_run: bool) -> None:
        if not dry_run:
            if isinstance(e, PipelineRateLimitError) or (
                isinstance(e, PipelineConnectivityError) and e.retryable
            ):
                self._safe_update_status(article.url, StoryStatus.UNPROCESSED)
            elif isinstance(e, PipelineException):
                self._safe_update_status(article.url, StoryStatus.SYSTEM_ERROR)

        error_cat = _error_category(e)
        if error_cat is not None:
            resolution_run = getattr(e, "resolution_run", None)
            dlq_id = "N/A"
            if self.dlq_adapter:
                dlq_arguments = dict(
                    url=article.url,
                    title=article.title or "",
                    original_text=e.original_text,
                    validation_issues=e.validation_issues,
                    failure_type=e.failure_type,
                    retry_count=e.retry_count,
                    metadata=e.metadata,
                    error_category=error_cat,
                )
                if resolution_run is not None:
                    dlq_arguments["resolution_run"] = resolution_run
                try:
                    dlq_id = self.dlq_adapter.log_failure(
                        **dlq_arguments
                    )
                except Exception as dlq_err:
                    logger.error(f"Failed to log {error_cat} failure to DLQ: {dlq_err}")
                    if not dry_run:
                        self._safe_update_status(article.url, StoryStatus.SYSTEM_ERROR)
                    raise dlq_err

            logger.error(
                f"{error_cat.capitalize()} failure. Reason: {e.failure_type}. "
                f"Issues: {e.validation_issues}. "
                f"Archived in DLQ: {dlq_id}"
            )
            if not dry_run:
                self._safe_update_status(article.url, StoryStatus.FAILED_DLQ)
            e.logged_to_dlq = True

        elif not isinstance(e, PipelineException):
            logger.error(f"Unexpected pipeline error: {e}")
            if not dry_run:
                self._safe_update_status(article.url, StoryStatus.SYSTEM_ERROR)
