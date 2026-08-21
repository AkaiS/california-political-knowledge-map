import logging
from typing import Protocol, List, Optional
from knowledge_map.config import settings as global_settings
from knowledge_map.schemas import (
    AdherenceReport,
    BillSessionResolutions,
    CoreferenceResolutionRun,
    LegislativeEventDates,
    SourceArticle,
    ArticleChunk,
    ExtractionResult,
    PipelineResult,
    ArticleStatus,
)
from knowledge_map.utils.chunking import chunk_article
from knowledge_map.core.bill_sessions import resolve_bill_sessions
from knowledge_map.core.legislative_events import resolve_legislative_event_dates

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
from knowledge_map.core.exceptions import (
    PipelineException,
    transport_failures_as_pipeline_errors,
)

class StoryPipeline:
    def __init__(
        self,
        db_adapter: DatabaseAdapter,
        embedding_adapter: EmbeddingAdapter,
        coreference_adapter: CoreferenceAdapter,
        extraction_adapter: EntityExtractionAdapter,
        status_tracker: StatusTracker,
        dlq_adapter: Optional[DeadLetterQueueAdapter] = None,
        settings = None,
    ) -> None:
        self.db_adapter = db_adapter
        self.embedding_adapter = embedding_adapter
        self.coreference_adapter = coreference_adapter
        self.extraction_adapter = extraction_adapter
        self.status_tracker = status_tracker
        self.dlq_adapter = dlq_adapter
        
        # Load default batch ingestion settings if not explicitly passed
        if settings is None:
            self.settings = global_settings.batch_ingestion
        else:
            self.settings = settings

    def run(self, article: SourceArticle, dry_run: bool = False) -> PipelineResult:
        logger.info(f"Starting pipeline run for article: {article.title or article.url}")
        
        if not dry_run:
            self.status_tracker.update_status(article.url, ArticleStatus.PROCESSING)

        try:
            # 1. Resolve coreferences
            logger.info("Resolving coreferences...")
            with transport_failures_as_pipeline_errors("coreference"):
                resolution_run = self.coreference_adapter.resolve(article.content)
            resolved_text = resolution_run.resolved_text

            # 2. Chunking
            logger.info("Chunking text...")
            chunks = chunk_article(resolved_text)

            # 3. Embedding
            logger.info("Generating embeddings...")
            with transport_failures_as_pipeline_errors("embedding"):
                embeddings = self.embedding_adapter.process_chunks(chunks)

            # 4. Extraction
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

            # 5. DB Persistence (skip if dry_run)
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

                # 6. Update status to COMPLETED
                self.status_tracker.update_status(article.url, ArticleStatus.COMPLETED)

            return PipelineResult(
                resolved_text=resolved_text,
                chunks=chunks,
                embeddings=embeddings,
                extractions=extractions,
            )
        except Exception as e:
            self._handle_pipeline_failure(e, article, dry_run)
            raise e

    def _safe_update_status(self, url: str, status: ArticleStatus) -> None:
        try:
            self.status_tracker.update_status(url, status)
        except Exception as status_err:
            logger.error(f"Failed to update status to {status}: {status_err}")

    def _handle_pipeline_failure(self, e: Exception, article: SourceArticle, dry_run: bool) -> None:
        if not dry_run:
            if isinstance(e, PipelineException):
                self._safe_update_status(article.url, ArticleStatus.UNPROCESSED)

        if isinstance(e, (CoreferenceResolutionError, ExtractionError)):
            error_cat = "coreference" if isinstance(e, CoreferenceResolutionError) else "extraction"
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
                        self._safe_update_status(article.url, ArticleStatus.SYSTEM_ERROR)
                    raise dlq_err

            logger.error(
                f"{error_cat.capitalize()} failure. Reason: {e.failure_type}. "
                f"Issues: {e.validation_issues}. "
                f"Archived in DLQ: {dlq_id}"
            )
            if not dry_run:
                self._safe_update_status(article.url, ArticleStatus.FAILED_DLQ)
            e.logged_to_dlq = True

        elif not isinstance(e, PipelineException):
            logger.error(f"Unexpected pipeline error: {e}")
            if not dry_run:
                self._safe_update_status(article.url, ArticleStatus.SYSTEM_ERROR)
