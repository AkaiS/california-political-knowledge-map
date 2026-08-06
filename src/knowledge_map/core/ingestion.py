import datetime
import json
import logging
import os

from knowledge_map.adapters.sqlite_db import get_story_links, get_unprocessed_stories
from knowledge_map.config import BatchIngestionSettings
from knowledge_map.config import settings as global_settings
from knowledge_map.core.exceptions import (
    PipelineLockError,
    PipelineRateLimitError,
    classify_exception,
)
from knowledge_map.core.pipeline import StoryPipeline
from knowledge_map.schemas import ArticleStatus, SourceArticle, StoryLink
from knowledge_map.utils.console import ConsoleNotifier

logger = logging.getLogger(__name__)

class BatchIngestionService:
    def __init__(
        self,
        pipeline: StoryPipeline,
        settings: BatchIngestionSettings | None = None
    ) -> None:
        self.pipeline = pipeline
        # Use settings module if none provided
        self.settings = settings or global_settings.batch_ingestion
        self.consecutive_failures = 0
        self.consecutive_rate_limit_failures = 0

    def _write_adherence_report(self) -> None:
        adapter = getattr(self.pipeline, "extraction_adapter", None)
        report = getattr(adapter, "adherence_report", None)
        if not isinstance(report, dict):
            return
        report_path = self.settings.adherence_report_path
        directory = os.path.dirname(report_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as report_file:
            json.dump(report, report_file, indent=2, sort_keys=True)
            report_file.write("\n")

    def run(self) -> None:
        """
        Runs the batch ingestion by fetching unprocessed stories and executing them through the pipeline.
        """
        # Fail-Fast Startup lock check
        if os.path.exists(self.settings.lock_file_path):
            logger.error(f"Pipeline lock file found at {self.settings.lock_file_path}. Aborting startup.")
            raise PipelineLockError(f"Pipeline is locked. Lock file exists at {self.settings.lock_file_path}")

        extraction_adapter = getattr(self.pipeline, "extraction_adapter", None)
        reset_report = getattr(extraction_adapter, "reset_adherence_report", None)
        if callable(reset_report):
            reset_report()

        try:
            self._run_stories()
        finally:
            self._write_adherence_report()

    def _run_stories(self) -> None:
        logger.info(f"Starting batch ingestion. Database path: {self.settings.db_path}")
        unprocessed = get_unprocessed_stories(self.settings.db_path)
        if not unprocessed:
            logger.info("No unprocessed stories found.")
            return

        logger.info(f"Found {len(unprocessed)} unprocessed stories to ingest.")
        for idx, story_dict in enumerate(unprocessed, 1):
            url = story_dict.get("url")
            title = story_dict.get("title") or url
            logger.info(f"[{idx}/{len(unprocessed)}] Processing story: {title}")

            try:
                article = SourceArticle(
                    url=url,
                    title=story_dict.get("title"),
                    author=story_dict.get("author"),
                    published_date=story_dict.get("published_date"),
                    content=story_dict.get("content") or "",
                    links=[
                        StoryLink(url=link["url"], text=link.get("text"))
                        for link in get_story_links(story_dict["id"], self.settings.db_path)
                    ],
                )

                self.pipeline.run(article)
                # Success: reset consecutive failures
                self.consecutive_failures = 0
                self.consecutive_rate_limit_failures = 0
            except PipelineRateLimitError as e:
                self.consecutive_rate_limit_failures += 1
                logger.warning(
                    f"Rate limit error processing story {title} "
                    f"(consecutive rate limit failures: {self.consecutive_rate_limit_failures}): {e}"
                )
                try:
                    self.pipeline.status_tracker.update_status(url, ArticleStatus.UNPROCESSED)
                except Exception as status_err:
                    logger.error(f"Failed to reset status to UNPROCESSED: {status_err}")
                if self.consecutive_rate_limit_failures >= 3:
                    lock_data = {
                        "timestamp": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
                        "component": e.component,
                        "error_message": str(e)
                    }
                    
                    # Ensure directory exists
                    os.makedirs(os.path.dirname(self.settings.lock_file_path), exist_ok=True)
                    
                    with open(self.settings.lock_file_path, "w") as f:
                        json.dump(lock_data, f, indent=2)

                    ConsoleNotifier.notify_lock_triggered(
                        component=e.component,
                        lock_file_path=self.settings.lock_file_path,
                        error_message=str(e)
                    )

                    logger.error(
                        f"Reached 3 consecutive rate limit failures. "
                        f"Pipeline locked at {self.settings.lock_file_path}."
                    )
                    raise PipelineLockError(
                        f"Pipeline locked due to consecutive rate limit failures on component: {e.component}"
                    )
                continue
            except Exception as e:
                if classify_exception(e):
                    logger.warning(f"Non-breaking error processing story {title}: {e}")
                else:
                    self.consecutive_failures += 1
                    logger.error(f"System error processing story {title} (consecutive: {self.consecutive_failures}): {e}")
                    try:
                        self.pipeline.status_tracker.update_status(url, ArticleStatus.SYSTEM_ERROR)
                    except Exception as status_err:
                        logger.error(f"Failed to update status to SYSTEM_ERROR: {status_err}")
                    
                    if self.consecutive_failures >= self.settings.consecutive_failures_limit:
                        logger.error(f"Reached limit of {self.settings.consecutive_failures_limit} consecutive system errors. Aborting batch.")
                        raise e

        logger.info("Batch ingestion run completed successfully.")
