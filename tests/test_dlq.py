import os
import json
import pytest
from unittest.mock import patch, mock_open
from knowledge_map.adapters.dlq import LocalFileDLQAdapter

def test_dlq_adapter_success(tmp_path):
    dlq_dir = tmp_path / "coreference_dlq"
    adapter = LocalFileDLQAdapter(directory=str(dlq_dir))
    
    url = "https://www.sacbee.com/news/local/article234.html"
    title = "Sacramento Bee Local News"
    original_text = "Newsom signed AB-5. He was happy."
    annotated_text = "Newsom signed AB-5. <ref entity=\"Gavin Newsom\">He</ref> was happy."
    validation_issues = ["Critic issue"]
    failure_type = "critic_rejection"
    retry_count = 2
    metadata = {
        "model": "gemma",
        "temperature": 0.0,
        "prompt_version": "1.0",
        "system_prompt": "You are a coref resolver"
    }
    
    res = adapter.log_failure(
        url=url,
        title=title,
        original_text=original_text,
        annotated_text=annotated_text,
        validation_issues=validation_issues,
        failure_type=failure_type,
        retry_count=retry_count,
        metadata=metadata
    )
    
    # Assert directory was created and contains exactly one file
    assert os.path.exists(dlq_dir)
    files = os.listdir(dlq_dir)
    assert len(files) == 1
    
    filename = files[0]
    assert res == filename
    # Check naming conventions: {domain}_{url_hash}_{timestamp}_{failure_type}_retry_{retry_count}.json
    parts = filename.split("_")
    assert len(parts) >= 6
    
    # Domain (www.sacbee.com or similar cleaned domain with replaced underscores)
    assert "sacbee" in parts[0]
    # URL Hash (SHA256 is 64 hex characters)
    assert len(parts[1]) == 64
    # Failure type and retry
    assert parts[-2] == "retry"
    assert parts[-1] == f"{retry_count}.json"
    
    # Read payload and assert contents
    filepath = dlq_dir / filename
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    assert data["url"] == url
    assert data["title"] == title
    assert data["original_text"] == original_text
    assert data["annotated_text"] == annotated_text
    assert data["validation_issues"] == validation_issues
    assert data["failure_type"] == failure_type
    assert data["retry_count"] == retry_count
    assert data["metadata"] == metadata
    assert "timestamp" in data

def test_dlq_adapter_write_failure(tmp_path, caplog):
    import logging
    # Use a non-existent root / invalid path to trigger OSError
    invalid_dir = "/nonexistent_root_dir_abc_123/dlq"
    adapter = LocalFileDLQAdapter(directory=invalid_dir)
    
    with pytest.raises(OSError):
        adapter.log_failure(
            url="http://example.com",
            title="Title",
            original_text="Original",
            annotated_text="Annotated",
            validation_issues=[],
            failure_type="structural_mismatch",
            retry_count=1,
            metadata={}
        )
        
    # Verify warning log was written
    assert any("Failed to write DLQ record" in record.message for record in caplog.records)
