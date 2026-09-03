"""Story Pipeline behavior after request-local retries are exhausted."""

import sqlite3

import httpx
import pytest
from pydantic_ai.exceptions import ModelHTTPError

from knowledge_map.adapters.sqlite_db import (
    SQLiteStatusTracker,
    get_unprocessed_stories,
    init_db,
    save_story,
)
from knowledge_map.config import BatchIngestionSettings
from knowledge_map.core.exceptions import PipelineConnectivityError
from knowledge_map.core.ingestion import BatchIngestionService
from knowledge_map.core.pipeline import StoryPipeline
from knowledge_map.schemas import (
    AdherenceReport,
    ExtractionResult,
    SourceArticle,
    Story,
)


class NoopDatabase:
    def ingest_article(self, article):
        pass

    def ingest_chunk(self, article, chunk, embedding):
        pass

    def ingest_chunk_extraction(self, chunk_id, extraction, bill_sessions=None, event_dates=None):
        pass

    def ingest_article_topics(self, article, policy_areas, assignments=None, bill_sessions=None):
        pass


class NoopPolicyAreas:
    def classify(self, resolved_text: str) -> list[str]:
        return []


class NoopEmbedding:
    def process_chunks(self, chunks):
        return [[0.1] * 3 for _ in chunks]


class NoopExtraction:
    @property
    def adherence_report(self):
        return AdherenceReport()

    def reset_adherence_report(self):
        pass

    def extract(self, chunk_text):
        return ExtractionResult(nodes=[], relationships=[])


class FailingCoreferenceAdapter:
    def __init__(self, error):
        self.error = error

    def resolve(self, content):
        raise self.error


class RecordingStatusTracker:
    def __init__(self):
        self.updates = []

    def update_status(self, url, status):
        self.updates.append((url, status))


@pytest.mark.parametrize("status_code", [429, 503])
def test_exhausted_retryable_pipeline_error_leaves_story_selectable_for_later_batch(
    tmp_path, status_code
):
    db_path = str(tmp_path / "stories.db")
    init_db(db_path)
    story = Story(
        title="Remote failure",
        url="https://example.com/remote-failure",
        content="The request was exhausted.",
    )
    save_story(story, db_path=db_path)

    pipeline = StoryPipeline(
        db_adapter=NoopDatabase(),
        embedding_adapter=NoopEmbedding(),
        coreference_adapter=FailingCoreferenceAdapter(
            ModelHTTPError(
                status_code=status_code, model_name="remote-model", body=None
            )
        ),
        extraction_adapter=NoopExtraction(),
        policy_area_adapter=NoopPolicyAreas(),
        status_tracker=SQLiteStatusTracker(db_path=db_path),
    )
    service = BatchIngestionService(
        pipeline=pipeline,
        settings=BatchIngestionSettings(
            db_path=db_path,
            adherence_report_path=str(tmp_path / "adherence.json"),
        ),
    )

    service.run()

    with sqlite3.connect(db_path) as connection:
        status = connection.execute(
            "SELECT status FROM stories WHERE url = ?", (story.url,)
        ).fetchone()[0]

    assert status == "UNPROCESSED"
    assert [row["url"] for row in get_unprocessed_stories(db_path)] == [story.url]


def test_nonretryable_model_http_error_is_translated_to_system_error():
    status_tracker = RecordingStatusTracker()
    pipeline = StoryPipeline(
        db_adapter=NoopDatabase(),
        embedding_adapter=NoopEmbedding(),
        coreference_adapter=FailingCoreferenceAdapter(
            ModelHTTPError(status_code=401, model_name="remote-model", body=None)
        ),
        extraction_adapter=NoopExtraction(),
        policy_area_adapter=NoopPolicyAreas(),
        status_tracker=status_tracker,
    )
    article = SourceArticle(
        url="https://example.com/unauthorized",
        title="Unauthorized",
        content="The provider rejected this request.",
    )

    with pytest.raises(PipelineConnectivityError) as exc_info:
        pipeline.run(article)

    assert exc_info.value.original_exception.status_code == 401
    assert not exc_info.value.retryable
    assert status_tracker.updates == [
        (article.url, "PROCESSING"),
        (article.url, "SYSTEM_ERROR"),
    ]


def test_exhausted_pipeline_connectivity_error_returns_story_to_unprocessed(tmp_path):
    db_path = str(tmp_path / "transport-stories.db")
    init_db(db_path)
    story = Story(
        title="Transport failure",
        url="https://example.com/transport-failure",
        content="The connection was exhausted.",
    )
    save_story(story, db_path=db_path)

    pipeline = StoryPipeline(
        db_adapter=NoopDatabase(),
        embedding_adapter=NoopEmbedding(),
        coreference_adapter=FailingCoreferenceAdapter(
            httpx.ConnectError("connection reset")
        ),
        extraction_adapter=NoopExtraction(),
        policy_area_adapter=NoopPolicyAreas(),
        status_tracker=SQLiteStatusTracker(db_path=db_path),
    )
    BatchIngestionService(
        pipeline=pipeline,
        settings=BatchIngestionSettings(
            db_path=db_path,
            adherence_report_path=str(tmp_path / "adherence.json"),
        ),
    ).run()

    with sqlite3.connect(db_path) as connection:
        status = connection.execute(
            "SELECT status FROM stories WHERE url = ?", (story.url,)
        ).fetchone()[0]

    assert status == "UNPROCESSED"
