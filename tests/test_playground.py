import pytest
from unittest.mock import MagicMock, patch
from playground import main, Neo4jManager, Neo4jConfigError, Neo4jConnectionError

@pytest.fixture(autouse=True)
def mock_ensure_vector_index(request):
    if "no_mock_ensure_index" in request.keywords:
        yield
    else:
        with patch("graph_db.Neo4jAdapter._ensure_vector_index", create=True) as m:
            yield m

def test_cli_clear_success(capsys):
    with patch("playground.Neo4jAdapter") as MockAdapter:
        mock_instance = MockAdapter.return_value
        
        try:
            main(["clear"])
        except SystemExit as e:
            assert e.code == 0
            
        MockAdapter.assert_called_once()
        mock_instance.clear_database.assert_called_once()
        mock_instance.close.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Neo4j database cleared successfully" in captured.out

def test_cli_clear_config_error(capsys):
    with patch("playground.Neo4jAdapter") as MockAdapter:
        MockAdapter.side_effect = Neo4jConfigError("NEO4J_URI environment variable is missing or empty.")
        
        with pytest.raises(SystemExit) as exc_info:
            main(["clear"])
        assert exc_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "Configuration Error:" in (captured.err + captured.out)
        assert "NEO4J_URI environment variable is missing" in (captured.err + captured.out)

def test_cli_clear_connection_error(capsys):
    with patch("playground.Neo4jAdapter") as MockAdapter:
        mock_instance = MockAdapter.return_value
        mock_instance.clear_database.side_effect = Neo4jConnectionError("Could not connect to Neo4j database")
        
        with pytest.raises(SystemExit) as exc_info:
            main(["clear"])
        assert exc_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "Connection Error:" in (captured.err + captured.out)
        assert "Could not connect to Neo4j database" in (captured.err + captured.out)

from schemas import ExtractionResult, Node, Relationship, ArticleChunk

@pytest.fixture
def mock_pipeline_deps():
    with patch("coreference.PydanticAICoreferenceAdapter.resolve", side_effect=lambda x: x) as mock_resolve, \
         patch("pipeline.chunk_article", side_effect=lambda text: [ArticleChunk(text=text, start_index=0, end_index=len(text), index=0)]) as mock_chunk, \
         patch("embedding.PydanticAIEmbeddingAdapter.process_chunks", side_effect=lambda chunks: [[0.1] * 768] * len(chunks)) as mock_process_chunks:
        yield {
            "resolve": mock_resolve,
            "chunk": mock_chunk,
            "process_chunks": mock_process_chunks
        }

def test_cli_run_dry_run_with_text(capsys, mock_pipeline_deps):
    mock_result = ExtractionResult(
        nodes=[Node(name="Gavin Newsom", label="PoliticalActor")],
        relationships=[]
    )
    with patch("extraction.PydanticAIEntityExtractionAdapter.extract", return_value=mock_result) as mock_extract:
        try:
            main(["run", "--dry-run", "--text", "My custom text"])
        except SystemExit as e:
            assert e.code == 0
            
        mock_extract.assert_called_once_with("My custom text")
        captured = capsys.readouterr()
        assert "Gavin Newsom" in captured.out
        assert "PoliticalActor" in captured.out

def test_cli_run_dry_run_fallback_text(capsys, mock_pipeline_deps):
    mock_result = ExtractionResult(
        nodes=[Node(name="Fallback Actor", label="PoliticalActor")],
        relationships=[]
    )
    with patch("playground.get_last_n_stories", return_value=[]), \
         patch("extraction.PydanticAIEntityExtractionAdapter.extract", return_value=mock_result) as mock_extract:
        try:
            main(["run", "--dry-run"])
        except SystemExit as e:
            assert e.code == 0
            
        mock_extract.assert_called_once()
        called_args, _ = mock_extract.call_args
        assert len(called_args[0]) > 0
        
        captured = capsys.readouterr()
        assert "Fallback Actor" in captured.out

def test_cli_run_dry_run_sqlite_text(capsys, mock_pipeline_deps):
    mock_result = ExtractionResult(
        nodes=[Node(name="SQLite Actor", label="PoliticalActor")],
        relationships=[]
    )
    mock_stories = [{"title": "My Title", "content": "Article body about politics"}]
    with patch("playground.get_last_n_stories", return_value=mock_stories), \
         patch("extraction.PydanticAIEntityExtractionAdapter.extract", return_value=mock_result) as mock_extract:
        try:
            main(["run", "--dry-run"])
        except SystemExit as e:
            assert e.code == 0
            
        mock_extract.assert_called_once_with("Article body about politics")
        
        captured = capsys.readouterr()
        assert "SQLite Actor" in captured.out

def test_cli_run_integration_all_stories(capsys, mock_pipeline_deps):
    mock_stories = [
        {"title": "Story 1", "url": "http://example.com/1", "content": "Content 1"},
        {"title": "Story 2", "url": "http://example.com/2", "content": "Content 2"}
    ]
    
    mock_result1 = ExtractionResult(nodes=[Node(name="Actor 1", label="PoliticalActor")], relationships=[])
    mock_result2 = ExtractionResult(nodes=[Node(name="Actor 2", label="PoliticalActor")], relationships=[])
    
    def side_effect(text, *args, **kwargs):
        if text == "Content 1":
            return mock_result1
        elif text == "Content 2":
            return mock_result2
        raise ValueError(f"Unexpected content: {text}")
        
    with patch("playground.Neo4jAdapter") as MockAdapter, \
         patch("playground.get_all_stories", return_value=mock_stories) as mock_get_all, \
         patch("extraction.PydanticAIEntityExtractionAdapter.extract", side_effect=side_effect) as mock_extract:
         
        mock_manager_instance = MockAdapter.return_value
        
        try:
            main(["run"])
        except SystemExit as e:
            assert e.code == 0
            
        MockAdapter.assert_called_once()
        mock_get_all.assert_called_once()
        
        assert mock_pipeline_deps["resolve"].call_count == 2
        assert mock_pipeline_deps["chunk"].call_count == 2
        
        assert mock_extract.call_count == 2
        mock_extract.assert_any_call("Content 1")
        mock_extract.assert_any_call("Content 2")
        
        assert mock_manager_instance.ingest_article.call_count == 2
        
        # Verify first ingest_article call
        called_art1 = mock_manager_instance.ingest_article.call_args_list[0][0][0]
        assert called_art1.url == "http://example.com/1"
        assert called_art1.title == "Story 1"
        
        # Verify second ingest_article call
        called_art2 = mock_manager_instance.ingest_article.call_args_list[1][0][0]
        assert called_art2.url == "http://example.com/2"
        assert called_art2.title == "Story 2"
        
        assert mock_manager_instance.ingest_chunk.call_count == 2
        # Verify first ingest_chunk call
        called_art1_chunk, called_chunk1, called_emb1 = mock_manager_instance.ingest_chunk.call_args_list[0][0]
        assert called_art1_chunk.url == "http://example.com/1"
        assert called_chunk1.text == "Content 1"
        assert called_chunk1.index == 0
        assert called_emb1 == [0.1] * 768
        
        # Verify second ingest_chunk call
        called_art2_chunk, called_chunk2, called_emb2 = mock_manager_instance.ingest_chunk.call_args_list[1][0]
        assert called_art2_chunk.url == "http://example.com/2"
        assert called_chunk2.text == "Content 2"
        assert called_chunk2.index == 0
        assert called_emb2 == [0.1] * 768
        
        assert mock_manager_instance.ingest_chunk_extraction.call_count == 2
        mock_manager_instance.ingest_chunk_extraction.assert_any_call(
            "http://example.com/1#chunk_0",
            mock_result1
        )
        mock_manager_instance.ingest_chunk_extraction.assert_any_call(
            "http://example.com/2#chunk_0",
            mock_result2
        )
        
        mock_manager_instance.close.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Successfully processed 2 stories" in captured.out

def test_cli_run_pipeline_integration(mock_pipeline_deps):
    mock_story = {
        "id": 1,
        "title": "Pipeline News",
        "url": "http://example.com/pipeline",
        "author": "Alice",
        "published_date": "2026-06-28",
        "content": "Newsom signed AB-5. He was happy."
    }
    
    mock_pipeline_deps["resolve"].side_effect = None
    mock_pipeline_deps["resolve"].return_value = "Gavin Newsom signed AB-5. Gavin Newsom was happy."
    
    mock_chunks = [
        ArticleChunk(text="Gavin Newsom signed AB-5.", start_index=0, end_index=25, index=0),
        ArticleChunk(text="Gavin Newsom was happy.", start_index=26, end_index=49, index=1)
    ]
    mock_pipeline_deps["chunk"].side_effect = None
    mock_pipeline_deps["chunk"].return_value = mock_chunks
    
    mock_extraction_chunk0 = ExtractionResult(
        nodes=[
            Node(name="Gavin Newsom", label="PoliticalActor"),
            Node(name="AB-5", label="PublicPolicy")
        ],
        relationships=[
            Relationship(source="Gavin Newsom", target="AB-5", relationship_type="SIGNED")
        ]
    )
    mock_extraction_chunk1 = ExtractionResult(
        nodes=[Node(name="Gavin Newsom", label="PoliticalActor")],
        relationships=[]
    )
    
    def mock_extract(text, *args, **kwargs):
        if "signed" in text:
            return mock_extraction_chunk0
        elif "happy" in text:
            return mock_extraction_chunk1
        return ExtractionResult(nodes=[], relationships=[])
        
    with patch("playground.Neo4jAdapter") as MockAdapter, \
         patch("playground.get_all_stories", return_value=[mock_story]), \
         patch("extraction.PydanticAIEntityExtractionAdapter.extract", side_effect=mock_extract) as mock_extract_entities:
         
        mock_manager_instance = MockAdapter.return_value
        
        main(["run"])
        
        mock_pipeline_deps["resolve"].assert_called_once_with("Newsom signed AB-5. He was happy.")
        mock_pipeline_deps["chunk"].assert_called_once_with("Gavin Newsom signed AB-5. Gavin Newsom was happy.")
        
        assert mock_manager_instance.ingest_article.call_count == 1
        called_art = mock_manager_instance.ingest_article.call_args[0][0]
        assert called_art.url == "http://example.com/pipeline"
        assert called_art.title == "Pipeline News"
        assert called_art.author == "Alice"
        assert called_art.published_date == "2026-06-28"
        
        assert mock_manager_instance.ingest_chunk.call_count == 2
        
        called_art1_chunk, called_chunk1, called_emb1 = mock_manager_instance.ingest_chunk.call_args_list[0][0]
        assert called_art1_chunk.url == "http://example.com/pipeline"
        assert called_chunk1.text == "Gavin Newsom signed AB-5."
        assert called_chunk1.index == 0
        assert called_emb1 == [0.1] * 768
        
        called_art2_chunk, called_chunk2, called_emb2 = mock_manager_instance.ingest_chunk.call_args_list[1][0]
        assert called_art2_chunk.url == "http://example.com/pipeline"
        assert called_chunk2.text == "Gavin Newsom was happy."
        assert called_chunk2.index == 1
        assert called_emb2 == [0.1] * 768
        
        assert mock_extract_entities.call_count == 2
        mock_extract_entities.assert_any_call("Gavin Newsom signed AB-5.")
        mock_extract_entities.assert_any_call("Gavin Newsom was happy.")
        
        assert mock_manager_instance.ingest_chunk_extraction.call_count == 2
        mock_manager_instance.ingest_chunk_extraction.assert_any_call(
            "http://example.com/pipeline#chunk_0",
            mock_extraction_chunk0
        )
        mock_manager_instance.ingest_chunk_extraction.assert_any_call(
            "http://example.com/pipeline#chunk_1",
            mock_extraction_chunk1
        )
        
        mock_manager_instance.close.assert_called_once()

def test_cli_analyze_success(capsys):
    with patch("playground.Neo4jAdapter") as MockAdapter:
        mock_instance = MockAdapter.return_value
        mock_instance.get_distinct_labels.return_value = ["Organization", "PoliticalActor"]
        
        try:
            main(["analyze"])
        except SystemExit as e:
            assert e.code == 0
            
        MockAdapter.assert_called_once()
        mock_instance.get_distinct_labels.assert_called_once()
        mock_instance.close.assert_called_once()
        
        captured = capsys.readouterr()
        assert "Distinct node labels" in captured.out
        assert "- Organization" in captured.out
        assert "- PoliticalActor" in captured.out

def test_cli_analyze_empty(capsys):
    with patch("playground.Neo4jAdapter") as MockAdapter:
        mock_instance = MockAdapter.return_value
        mock_instance.get_distinct_labels.return_value = []
        
        try:
            main(["analyze"])
        except SystemExit as e:
            assert e.code == 0
            
        MockAdapter.assert_called_once()
        mock_instance.get_distinct_labels.assert_called_once()
        mock_instance.close.assert_called_once()
        
        captured = capsys.readouterr()
        assert "No node labels found in the database." in captured.out

def test_cli_analyze_connection_error(capsys):
    with patch("playground.Neo4jAdapter") as MockAdapter:
        mock_instance = MockAdapter.return_value
        mock_instance.get_distinct_labels.side_effect = Neo4jConnectionError("Could not connect to Neo4j database")
        
        with pytest.raises(SystemExit) as exc_info:
            main(["analyze"])
        assert exc_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "Connection Error:" in (captured.err + captured.out)
        assert "Could not connect to Neo4j database" in (captured.err + captured.out)

def test_cli_analyze_duplicates_found(capsys):
    mock_manager = MagicMock()
    mock_manager.get_distinct_labels.return_value = ["PoliticalActor"]
    mock_manager.get_nodes_by_label.return_value = ["Gavin Newsom", "Gavin Newsome", "Jerry Brown"]
    
    mock_embedder = MagicMock()
    mock_embedding_result = MagicMock()
    mock_embedding_result.embeddings = [
        [1.0, 0.0, 0.0],  # Gavin Newsom
        [0.9, 0.1, 0.0],  # Gavin Newsome
        [0.0, 1.0, 0.0]   # Jerry Brown
    ]
    async def fake_embed_documents(inputs, settings=None):
        return mock_embedding_result
    mock_embedder.embed_documents.side_effect = fake_embed_documents

    with patch("playground.Neo4jAdapter", return_value=mock_manager), \
         patch("playground.get_embedding_embedder", return_value=mock_embedder):
        try:
            main(["analyze"])
        except SystemExit as e:
            assert e.code == 0
            
    captured = capsys.readouterr()
    assert "Distinct node labels:" in captured.out
    assert "- PoliticalActor" in captured.out
    assert "Potential duplicates in label 'PoliticalActor':" in captured.out
    assert "Gavin Newsom" in captured.out
    assert "Gavin Newsome" in captured.out
    assert "Jerry Brown" not in captured.out

def test_cli_analyze_no_duplicates(capsys):
    mock_manager = MagicMock()
    mock_manager.get_distinct_labels.return_value = ["PoliticalActor"]
    mock_manager.get_nodes_by_label.return_value = ["Gavin Newsom", "Jerry Brown"]
    
    mock_embedder = MagicMock()
    mock_embedding_result = MagicMock()
    mock_embedding_result.embeddings = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0]
    ]
    async def fake_embed_documents(inputs, settings=None):
        return mock_embedding_result
    mock_embedder.embed_documents.side_effect = fake_embed_documents

    with patch("playground.Neo4jAdapter", return_value=mock_manager), \
         patch("playground.get_embedding_embedder", return_value=mock_embedder):
        try:
            main(["analyze"])
        except SystemExit as e:
            assert e.code == 0
            
    captured = capsys.readouterr()
    assert "Distinct node labels:" in captured.out
    assert "- PoliticalActor" in captured.out
    assert "Potential duplicates" not in captured.out

def test_cli_analyze_too_few_nodes(capsys):
    mock_manager = MagicMock()
    mock_manager.get_distinct_labels.return_value = ["PoliticalActor"]
    mock_manager.get_nodes_by_label.return_value = ["Gavin Newsom"]
    
    mock_embedder = MagicMock()
    with patch("playground.Neo4jAdapter", return_value=mock_manager), \
         patch("playground.get_embedding_embedder", return_value=mock_embedder):
        try:
            main(["analyze"])
        except SystemExit as e:
            assert e.code == 0
            
    mock_embedder.embed_documents.assert_not_called()
    captured = capsys.readouterr()
    assert "Distinct node labels:" in captured.out
