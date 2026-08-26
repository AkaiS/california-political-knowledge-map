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


class CoreferenceSettings(BaseModel):
    """What bounds one Coreference Resolution Run.

    ``max_critic_rounds`` counts correction rounds after the annotator's first
    pass, separately from the agents' own structured-output retry budgets.
    """

    max_critic_rounds: int = Field(
        default_factory=lambda: int(
            os.environ.get("COREFERENCE_MAX_CRITIC_ROUNDS", 3)
        ),
        description="Critic rounds allowed beyond the annotator's first pass",
    )
    request_limit: int = Field(
        default_factory=lambda: int(os.environ.get("COREFERENCE_REQUEST_LIMIT", 50)),
        description="Total model requests allowed across one resolution",
    )
    total_tokens_limit: int = Field(
        default_factory=lambda: int(
            os.environ.get("COREFERENCE_TOTAL_TOKENS_LIMIT", 500_000)
        ),
        description="Total tokens allowed across one resolution",
    )


class BatchIngestionSettings(BaseModel):
    """What batch ingestion owns: the failure lock, the queue, and the report.

    Retry attempts, backoff and the rate limit wait cap are
    ``TransportSettings``, not here.
    """

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
    coreference: CoreferenceSettings = CoreferenceSettings()
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

