import os
from pydantic import BaseModel, Field

class ChunkingSettings(BaseModel):
    size: int = Field(default=512, description="Default chunk size (characters/tokens)")
    overlap_pct: float = Field(default=0.10, description="Overlap percentage as decimal")

class EmbeddingSettings(BaseModel):
    dimension: int = Field(default=768, description="Vector dimension size for Neo4j index")

class BatchIngestionSettings(BaseModel):
    max_retries: int = Field(
        default_factory=lambda: int(os.environ.get("BATCH_MAX_RETRIES", 3)),
        description="Maximum retries for connectivity errors"
    )
    backoff_factor: float = Field(
        default_factory=lambda: float(os.environ.get("BATCH_BACKOFF_FACTOR", 2.0)),
        description="Multiplier applied to exponential backoff delay"
    )
    rate_limit_wait_cap: int = Field(
        default_factory=lambda: int(os.environ.get("BATCH_RATE_LIMIT_WAIT_CAP", 120)),
        description="Max delay in seconds to wait for Rate-After"
    )
    consecutive_failures_limit: int = Field(
        default_factory=lambda: int(os.environ.get("BATCH_CONSECUTIVE_FAILURES_LIMIT", 3)),
        description="Max consecutive failures before lock"
    )
    lock_file_path: str = Field(
        default_factory=lambda: os.environ.get("BATCH_LOCK_FILE_PATH", ".scratch/pipeline.lock"),
        description="Path to lock file"
    )
    db_path: str = Field(
        default_factory=lambda: os.environ.get("SQLITE_DB_PATH", "document_store.db"),
        description="Path to SQLite database"
    )

class Settings(BaseModel):
    chunking: ChunkingSettings = ChunkingSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    batch_ingestion: BatchIngestionSettings = BatchIngestionSettings()

settings = Settings()

