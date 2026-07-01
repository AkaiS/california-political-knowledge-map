import os
import json
import logging
import datetime
import urllib.parse
import hashlib

logger = logging.getLogger(__name__)

class LocalFileDLQAdapter:
    def __init__(self, directory: str = ".scratch/coreference_dlq") -> None:
        self.directory = directory

    def log_failure(
        self,
        url: str,
        title: str,
        original_text: str,
        annotated_text: str,
        validation_issues: list[str],
        failure_type: str,
        retry_count: int,
        metadata: dict
    ) -> None:
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        # Parse domain from URL
        try:
            parsed_url = urllib.parse.urlparse(url)
            domain = parsed_url.netloc or "unknown-domain"
        except Exception:
            domain = "unknown-domain"
            
        # Clean domain for filename safety and replace underscores with hyphens
        domain_clean = "".join(c for c in domain if c.isalnum() or c in ".-").replace("_", "-")
        if not domain_clean:
            domain_clean = "unknown-domain"
            
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
        
        # Filename friendly timestamp format (replace colons and dots)
        timestamp_safe = timestamp.replace(":", "-").replace(".", "-")
        
        # Clean failure type (replace underscores with hyphens)
        failure_type_clean = failure_type.replace("_", "-")
        
        filename = f"{domain_clean}_{url_hash}_{timestamp_safe}_{failure_type_clean}_retry_{retry_count}.json"
        filepath = os.path.join(self.directory, filename)
        
        payload = {
            "url": url,
            "title": title,
            "original_text": original_text,
            "annotated_text": annotated_text,
            "validation_issues": validation_issues,
            "failure_type": failure_type,
            "timestamp": timestamp,
            "retry_count": retry_count,
            "metadata": metadata
        }
        
        try:
            # Ensure the directory exists
            os.makedirs(self.directory, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            return filename
        except OSError as e:
            logger.warning(f"Failed to write DLQ record to filesystem: {e}", exc_info=True)
            raise e
