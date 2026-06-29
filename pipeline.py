import logging
from typing import Protocol, List, Optional
from schemas import SourceArticle, ArticleChunk, ExtractionResult, PipelineResult
from chunking import chunk_article

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

class StoryPipeline:
    def __init__(
        self,
        db_adapter: DatabaseAdapter,
        embedding_adapter: EmbeddingAdapter,
        coreference_adapter: CoreferenceAdapter,
        extraction_adapter: EntityExtractionAdapter,
    ) -> None:
        self.db_adapter = db_adapter
        self.embedding_adapter = embedding_adapter
        self.coreference_adapter = coreference_adapter
        self.extraction_adapter = extraction_adapter

    def run(self, article: SourceArticle, dry_run: bool = False) -> PipelineResult:
        logger.info(f"Starting pipeline run for article: {article.title or article.url}")
        
        # 1. Resolve coreferences
        logger.info("Resolving coreferences...")
        resolved_text = self.coreference_adapter.resolve(article.content)

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

        return PipelineResult(
            resolved_text=resolved_text,
            chunks=chunks,
            embeddings=embeddings,
            extractions=extractions
        )
