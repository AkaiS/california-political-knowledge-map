import logging
from typing import Protocol, List, Optional
from knowledge_map.schemas import SourceArticle, ArticleChunk, ExtractionResult, PipelineResult, ArticleStatus
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
        extraction: ExtractionResult
    ) -> None:
        ...

class EmbeddingAdapter(Protocol):
    def process_chunks(self, chunks: List[ArticleChunk]) -> List[List[float]]:
        ...

class CoreferenceAdapter(Protocol):
    def resolve(self, content: str) -> str:
        ...

class EntityExtractionAdapter(Protocol):
    def extract(self, chunk_text: str) -> ExtractionResult:
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
        metadata: dict
    ) -> None:
        ...

class StatusTracker(Protocol):
    def update_status(self, url: str, status: str) -> None:
        ...

from knowledge_map.adapters.coreference import CoreferenceResolutionError
from knowledge_map.adapters.extraction import ExtractionError

class StoryPipeline:
    def __init__(
        self,
        db_adapter: DatabaseAdapter,
        embedding_adapter: EmbeddingAdapter,
        coreference_adapter: CoreferenceAdapter,
        extraction_adapter: EntityExtractionAdapter,
        status_tracker: StatusTracker,
        dlq_adapter: Optional[DeadLetterQueueAdapter] = None,
    ) -> None:
        self.db_adapter = db_adapter
        self.embedding_adapter = embedding_adapter
        self.coreference_adapter = coreference_adapter
        self.extraction_adapter = extraction_adapter
        self.status_tracker = status_tracker
        self.dlq_adapter = dlq_adapter

    def run(self, article: SourceArticle, dry_run: bool = False) -> PipelineResult:
        logger.info(f"Starting pipeline run for article: {article.title or article.url}")
        
        if not dry_run:
            self.status_tracker.update_status(article.url, ArticleStatus.PROCESSING)

        try:
            # 1. Resolve coreferences
            logger.info("Resolving coreferences...")
            try:
                resolved_text = self.coreference_adapter.resolve(article.content)
            except CoreferenceResolutionError as e:
                if self.dlq_adapter:
                    self.dlq_adapter.log_failure(
                        url=article.url,
                        title=article.title or "",
                        original_text=e.original_text,
                        annotated_text=e.annotated_text,
                        validation_issues=e.validation_issues,
                        failure_type=e.failure_type,
                        retry_count=e.retry_count,
                        metadata=e.metadata
                    )

                if not dry_run:
                    self.status_tracker.update_status(article.url, ArticleStatus.FAILED_DLQ)
                e.logged_to_dlq = True
                raise e

            # 2. Chunking
            logger.info("Chunking text...")
            chunks = chunk_article(resolved_text)

            # 3. Embedding
            logger.info("Generating embeddings...")
            embeddings = self.embedding_adapter.process_chunks(chunks)

            # 4. Extraction
            logger.info("Extracting entities...")
            extractions = []
            for idx, chunk in enumerate(chunks):
                logger.info(f"Extracting chunk {idx}...")
                extraction = self.extraction_adapter.extract(chunk.text)
                extractions.append(extraction)

            # 5. DB Persistence (skip if dry_run)
            if not dry_run:
                logger.info("Ingesting article and chunks into DB...")
                self.db_adapter.ingest_article(article)
                for idx, chunk in enumerate(chunks):
                    chunk_id = f"{article.url}#chunk_{idx}"
                    embedding = embeddings[idx] if idx < len(embeddings) else []
                    self.db_adapter.ingest_chunk(article, chunk, embedding)
                    self.db_adapter.ingest_chunk_extraction(chunk_id, extractions[idx])

                # 6. Update status to COMPLETED
                self.status_tracker.update_status(article.url, ArticleStatus.COMPLETED)

            return PipelineResult(
                resolved_text=resolved_text,
                chunks=chunks,
                embeddings=embeddings,
                extractions=extractions
            )
        except Exception as e:
            if isinstance(e, ExtractionError):
                if self.dlq_adapter:
                    self.dlq_adapter.log_failure(
                        url=article.url,
                        title=article.title or "",
                        original_text=e.original_text,
                        annotated_text="",
                        validation_issues=e.validation_issues,
                        failure_type=e.failure_type,
                        retry_count=e.retry_count,
                        metadata=e.metadata
                    )
                if not dry_run:
                    try:
                        self.status_tracker.update_status(article.url, ArticleStatus.FAILED_DLQ)
                    except Exception as status_err:
                        logger.error(f"Failed to update status to FAILED_DLQ: {status_err}")
                e.logged_to_dlq = True
            elif not isinstance(e, CoreferenceResolutionError):
                logger.error(f"Unexpected pipeline error: {e}")
                if not dry_run:
                    try:
                        self.status_tracker.update_status(article.url, ArticleStatus.SYSTEM_ERROR)
                    except Exception as status_err:
                        logger.error(f"Failed to update status to SYSTEM_ERROR: {status_err}")
            raise e
