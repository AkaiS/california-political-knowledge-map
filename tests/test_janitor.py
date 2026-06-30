import os
import json
import pytest
from unittest.mock import patch, MagicMock
from knowledge_map.cli.main import main

def test_cli_janitor_no_lock_file(capsys):
    # Test janitor command when no lock file exists
    orig_exists = os.path.exists
    def mock_exists(path):
        if "pipeline.lock" in str(path):
            return False
        return orig_exists(path)

    with patch("os.path.exists", side_effect=mock_exists):
        try:
            main(["janitor"])
        except SystemExit as e:
            assert e.code == 0
        captured = capsys.readouterr()
        assert "No active pipeline lock found" in captured.out


def test_cli_janitor_health_check_passes(tmp_path, capsys):
    # Test janitor command when lock file exists, health check passes, and lock file is deleted
    lock_file = tmp_path / "pipeline.lock"
    lock_data = {
        "timestamp": "2026-06-30T12:00:00Z",
        "component": "embedding",
        "error_message": "Rate limit hit"
    }
    with open(lock_file, "w") as f:
        json.dump(lock_data, f)

    with patch("knowledge_map.config.settings.batch_ingestion.lock_file_path", str(lock_file)), \
         patch("knowledge_map.cli.main.PydanticAIEmbeddingAdapter") as MockEmbedding:
         
        mock_embedding_instance = MockEmbedding.return_value
        mock_embedding_instance.health_check.return_value = True

        try:
            main(["janitor"])
        except SystemExit as e:
            assert e.code == 0

        # Verify health check was called
        mock_embedding_instance.health_check.assert_called_once()
        # Verify lock file was deleted
        assert not os.path.exists(str(lock_file))
        
        captured = capsys.readouterr()
        assert "Component 'embedding' health check passed" in captured.out
        assert "Deleted pipeline lock file" in captured.out

def test_cli_janitor_health_check_fails(tmp_path, capsys):
    # Test janitor command when lock file exists, health check fails, and lock file is NOT deleted
    lock_file = tmp_path / "pipeline.lock"
    lock_data = {
        "timestamp": "2026-06-30T12:00:00Z",
        "component": "coreference",
        "error_message": "Rate limit hit"
    }
    with open(lock_file, "w") as f:
        json.dump(lock_data, f)

    with patch("knowledge_map.config.settings.batch_ingestion.lock_file_path", str(lock_file)), \
         patch("knowledge_map.cli.main.PydanticAICoreferenceAdapter") as MockCoref:
         
        mock_coref_instance = MockCoref.return_value
        mock_coref_instance.health_check.return_value = False

        with pytest.raises(SystemExit) as exc_info:
            main(["janitor"])
        
        assert exc_info.value.code == 1
        # Verify health check was called
        mock_coref_instance.health_check.assert_called_once()
        # Verify lock file is NOT deleted
        assert os.path.exists(str(lock_file))

        captured = capsys.readouterr()
        assert "Component 'coreference' health check failed" in (captured.err + captured.out)
        assert "Pipeline remains locked" in (captured.err + captured.out)

def test_cli_janitor_unknown_component(tmp_path, capsys):
    # Test janitor command when lock file exists with an unknown component
    lock_file = tmp_path / "pipeline.lock"
    lock_data = {
        "timestamp": "2026-06-30T12:00:00Z",
        "component": "unknown_component_name",
        "error_message": "Some error"
    }
    with open(lock_file, "w") as f:
        json.dump(lock_data, f)

    with patch("knowledge_map.config.settings.batch_ingestion.lock_file_path", str(lock_file)):
        with pytest.raises(SystemExit) as exc_info:
            main(["janitor"])
        
        assert exc_info.value.code == 1
        assert os.path.exists(str(lock_file))
        
        captured = capsys.readouterr()
        assert "Unknown component 'unknown_component_name' in lock file" in (captured.err + captured.out)
