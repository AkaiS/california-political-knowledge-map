import logging
import time
from typing import Protocol, List, Optional
from knowledge_map.config import settings as global_settings
from knowledge_map.schemas import AdherenceReport, BillSessionResolutions, SourceArticle, ArticleChunk, ExtractionResult, PipelineResult, ArticleStatus
from knowledge_map.utils.chunking import chunk_article
from knowledge_map.core.bill_sessions import resolve_bill_sessions

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
        published_date: str | None = None,
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
    def resolve(self, content: str) -> str:
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
        annotated_text: str,
        validation_issues: List[str],
        failure_type: str,
        retry_count: int,
        metadata: dict,
        error_category: str = "coreference"
    ) -> str:
        ...

class StatusTracker(Protocol):
    def update_status(self, url: str, status: str) -> None:
        ...

from knowledge_map.adapters.coreference import CoreferenceResolutionError
from knowledge_map.adapters.extraction import ExtractionError
from knowledge_map.core.exceptions import (
    classify_api_error,
    get_retry_after,
    PipelineException,
    PipelineRateLimitError,
    PipelineConnectivityError,
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

    def _execute_with_retry(self, component: str, func, *args, **kwargs):
        max_retries = self.settings.max_retries
        backoff_factor = self.settings.backoff_factor
        rate_limit_wait_cap = self.settings.rate_limit_wait_cap
        
        connectivity_attempts = 0
        rate_limit_attempts = 0
        
        while True:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                err_type = classify_api_error(e)
                
                if err_type == "RATE_LIMIT":
                    retry_after = get_retry_after(e)
                    if retry_after is not None:
                        if retry_after > rate_limit_wait_cap:
                            logger.warning(
                                f"[{component}] Rate limit Retry-After {retry_after}s exceeds "
                                f"cap of {rate_limit_wait_cap}s. Skipping article."
                            )
                            raise PipelineRateLimitError(
                                message=f"Rate limit Retry-After {retry_after}s exceeds cap of {rate_limit_wait_cap}s",
                                component=component,
                                original_exception=e
                            )
                        
                        logger.info(f"[{component}] Rate limit hit. Sleeping for {retry_after}s (Retry-After) before retry.")
                        time.sleep(retry_after)
                        rate_limit_attempts += 1
                        continue
                    else:
                        # Missing Retry-After header
                        if rate_limit_attempts < max_retries:
                            delay = 15 * (backoff_factor ** rate_limit_attempts)
                            logger.info(
                                f"[{component}] Rate limit hit (no Retry-After). "
                                f"Sleeping for {delay}s (attempt {rate_limit_attempts + 1}/{max_retries}) before retry."
                            )
                            time.sleep(delay)
                            rate_limit_attempts += 1
                            continue
                        else:
                            logger.error(f"[{component}] Rate limit retries exhausted.")
                            raise PipelineRateLimitError(
                                message=f"Rate limit retries exhausted",
                                component=component,
                                original_exception=e
                            )
                            
                elif err_type == "CONNECTIVITY":
                    if connectivity_attempts < max_retries:
                        delay = backoff_factor * (2 ** connectivity_attempts)
                        logger.info(
                            f"[{component}] Connectivity error. "
                            f"Sleeping for {delay}s (attempt {connectivity_attempts + 1}/{max_retries}) before retry."
                        )
                        time.sleep(delay)
                        connectivity_attempts += 1
                        continue
                    else:
                        logger.error(f"[{component}] Connectivity retries exhausted.")
                        raise PipelineConnectivityError(
                            message=f"Connectivity retries exhausted",
                            component=component,
                            original_exception=e
                        )
                else:
                    # Propagate other exceptions directly
                    raise e

    def run(self, article: SourceArticle, dry_run: bool = False) -> PipelineResult:
        logger.info(f"Starting pipeline run for article: {article.title or article.url}")
        
        if not dry_run:
            self.status_tracker.update_status(article.url, ArticleStatus.PROCESSING)

        try:
            # 1. Resolve coreferences
            logger.info("Resolving coreferences...")
            resolved_text = self._execute_with_retry("coreference", self.coreference_adapter.resolve, article.content)

            # 2. Chunking
            logger.info("Chunking text...")
            chunks = chunk_article(resolved_text)

            # 3. Embedding
            logger.info("Generating embeddings...")
            embeddings = self._execute_with_retry("embedding", self.embedding_adapter.process_chunks, chunks)

            # 4. Extraction
            logger.info("Extracting entities...")
            extractions = []
            for idx, chunk in enumerate(chunks):
                logger.info(f"Extracting chunk {idx}...")
                extraction = self._execute_with_retry("extraction", self.extraction_adapter.extract, chunk.text)
                extractions.append(extraction)

            bill_sessions = resolve_bill_sessions(article, extractions)

            # 5. DB Persistence (skip if dry_run)
            if not dry_run:
                logger.info("Ingesting article and chunks into DB...")
                self.db_adapter.ingest_article(article)
                for idx, chunk in enumerate(chunks):
                    chunk_id = f"{article.url}#chunk_{idx}"
                    embedding = embeddings[idx] if idx < len(embeddings) else []
                    self.db_adapter.ingest_chunk(article, chunk, embedding)
                    # The publication date is the Legislative Event date of last
                    # resort: an event the article dated no other way is stamped
                    # with it and flagged inferred.
                    self.db_adapter.ingest_chunk_extraction(
                        chunk_id, extractions[idx], bill_sessions, article.published_date
                    )

                # 6. Update status to COMPLETED
                self.status_tracker.update_status(article.url, ArticleStatus.COMPLETED)

            return PipelineResult(
                resolved_text=resolved_text,
                chunks=chunks,
                embeddings=embeddings,
                extractions=extractions
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
            annotated = getattr(e, "annotated_text", "")
            dlq_id = "N/A"
            if self.dlq_adapter:
                try:
                    dlq_id = self.dlq_adapter.log_failure(
                        url=article.url,
                        title=article.title or "",
                        original_text=e.original_text,
                        annotated_text=annotated,
                        validation_issues=e.validation_issues,
                        failure_type=e.failure_type,
                        retry_count=e.retry_count,
                        metadata=e.metadata,
                        error_category=error_cat
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
