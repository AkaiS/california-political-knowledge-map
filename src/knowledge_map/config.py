import os
from collections.abc import Callable

from pydantic import BaseModel, Field

from knowledge_map.schemas.model_deployment import ModelRequestSettings


def _optional_environment_value[ValueT](
    name: str, convert: Callable[[str], ValueT]
) -> ValueT | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return convert(value)


def configured_temperature() -> float:
    """Return the configured sampling temperature."""

    return float(os.environ.get("LLM_TEMPERATURE") or 0.0)


def configured_thinking() -> bool:
    """Return whether configured chat requests enable thinking."""

    return (os.environ.get("LLM_THINKING") or "off").strip().lower() in {
        "1",
        "on",
        "true",
        "yes",
    }


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
            os.environ.get("LLM_TRANSPORT_REQUEST_TIMEOUT", 3600.0)
        ),
        description="Per-request timeout in seconds",
    )


def configured_model_request_settings() -> ModelRequestSettings:
    """Resolve the shared, non-secret settings for one Model Deployment."""

    transport = TransportSettings()
    return ModelRequestSettings(
        temperature=configured_temperature(),
        top_p=_optional_environment_value("LLM_TOP_P", float),
        top_k=_optional_environment_value("LLM_TOP_K", int),
        thinking=configured_thinking(),
        reasoning_effort=_optional_environment_value(
            "LLM_REASONING_EFFORT", lambda value: value.strip()
        ),
        max_tokens=_optional_environment_value("LLM_MAX_TOKENS", int),
        timeout=transport.request_timeout,
        max_attempts=transport.max_attempts,
        rate_limit_wait_cap=transport.rate_limit_wait_cap,
    )


class CoreferenceSettings(BaseModel):
    """What bounds one Coreference Resolution Run.

    ``max_critic_rounds`` counts correction rounds after the annotator's first
    pass, separately from the agents' own structured-output retry budgets.

    The span budget bounds what the annotator may return for one article,
    as a rate rather than a constant. See the engineering log, 2026-09-08,
    for the measurements the rate was chosen from.
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
    spans_per_hundred_words: int = Field(
        default_factory=lambda: int(
            os.environ.get("COREFERENCE_SPANS_PER_HUNDRED_WORDS", 25)
        ),
        description="Mention Spans the annotator may return per 100 words",
    )
    min_span_budget: int = Field(
        default_factory=lambda: int(
            os.environ.get("COREFERENCE_MIN_SPAN_BUDGET", 60)
        ),
        description="Span budget floor, for articles too short to earn one",
    )
    tokens_per_span: int = Field(
        default_factory=lambda: int(
            os.environ.get("COREFERENCE_TOKENS_PER_SPAN", 32)
        ),
        description="Output tokens budgeted per Mention Span",
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


def document_store_path() -> str:
    """Locate the SQLite document store the application is configured to use.

    The environment is read at call time so a process configured after import
    still reaches the same store as the application.
    """
    return os.environ.get("SQLITE_DB_PATH", settings.batch_ingestion.db_path)


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
