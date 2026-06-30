import logging
from typing import Optional

from knowledge_map.config import Settings, BatchIngestionSettings
from knowledge_map.adapters.sqlite_db import get_unprocessed_stories
from knowledge_map.schemas import SourceArticle
from knowledge_map.core.pipeline import StoryPipeline

logger = logging.getLogger(__name__)

class BatchIngestionService:
    def __init__(
        self,
        pipeline: StoryPipeline,
        settings: Optional[BatchIngestionSettings] = None
    ) -> None:
        self.pipeline = pipeline
        # Use settings module if none provided
        from knowledge_map.config import settings as global_settings
        self.settings = settings or global_settings.batch_ingestion

    def run(self) -> None:
        """
        Runs the batch ingestion by fetching unprocessed stories and executing them through the pipeline.
        """
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

            article = SourceArticle(
                url=url,
                title=story_dict.get("title"),
                author=story_dict.get("author"),
                published_date=story_dict.get("published_date"),
                content=story_dict.get("content") or ""
            )

            # In Issue 01, any exception from the pipeline propagates directly
            self.pipeline.run(article)

        logger.info("Batch ingestion run completed successfully.")
