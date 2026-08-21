import os

from pydantic import BaseModel, Field


class ChunkingSettings(BaseModel):
    size: int = Field(default=512, description="Default chunk size (characters/tokens)")
    overlap_pct: float = Field(default=0.10, description="Overlap percentage as decimal")

class EmbeddingSettings(BaseModel):
    dimension: int = Field(default=768, description="Vector dimension size for Neo4j index")

class TransportSettings(BaseModel):
    """How the HTTP client behind every LLM model retries a failed request."""

    max_attempts: int = Field(
        default_factory=lambda: int(os.environ.get("LLM_TRANSPORT_MAX_ATTEMPTS", 3)),
        description="Total attempts per HTTP request before the failure is re-raised",
    )
    rate_limit_wait_cap: int = Field(
        default_factory=lambda: int(
            os.environ.get("LLM_TRANSPORT_RATE_LIMIT_WAIT_CAP", 120)
        ),
        description="Maximum seconds to honour from a parsed Retry-After header",
    )
    request_timeout: float = Field(
        default_factory=lambda: float(
            os.environ.get("LLM_TRANSPORT_REQUEST_TIMEOUT", 600.0)
        ),
        description="Per-request timeout in seconds",
    )


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
    adherence_report_path: str = Field(
        default_factory=lambda: os.environ.get(
            "EXTRACTION_ADHERENCE_REPORT_PATH", ".scratch/extraction-adherence-report.json"
        ),
        description="Per-run extraction adherence report path",
    )
    url_path_blocklist: list[str] = Field(
        default=["/sports/", "/recipes/", "/obituaries/", "/author/", "/category/", "/tag/", "/search/"],
        description="Global fallback URL path blocklist"
    )

class Settings(BaseModel):
    chunking: ChunkingSettings = ChunkingSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    transport: TransportSettings = TransportSettings()
    batch_ingestion: BatchIngestionSettings = BatchIngestionSettings()

settings = Settings()


POLITICAL_RELEVANCE_KEYWORDS = [
    "california", "sacramento", "newsom", "legislature", "assembly", "senate",
    "lobbyist", "lobbying", "election", "ballot", "veto", "governor", "democrat",
    "republican", "gop", "mayor", "city council", "supervisors", "proposition", "prop", "tax",
    "industry", "energy", "housing", "climate", "transportation", "education"
]

NEGATIVE_RELEVANCE_KEYWORDS = [
    "sports", "lifestyle", "recipe", "food", "dining", "travel", "obituary",
    "obituaries", "fashion", "entertainment", "movie", "concert", "music",
    "horoscope", "crossword", "weather", "gardening"
]

SECONDARY_RELEVANCE_KEYWORDS = [
    "local", "community", "development", "police", "crime", "school board",
    "traffic", "transit", "resident", "neighborhood", "county", "district",
    "city", "regional"
]

