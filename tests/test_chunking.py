import pytest
from chunking import chunk_article
from schemas import ArticleChunk

def test_default_chunking_behavior():
    # A text of about 3000 characters (3x the default chunk size of 1000)
    sentence = "Governor Gavin Newsom announced a new legislative proposal today regarding California water infrastructure projects. "
    text = sentence * 25
    
    chunks = chunk_article(text)
    
    # Check that chunks are returned and are ArticleChunk models
    assert len(chunks) > 1
    assert all(isinstance(c, ArticleChunk) for c in chunks)
    
    # Check that indices and start/end boundaries align
    for idx, c in enumerate(chunks):
        assert c.index == idx
        assert c.start_index >= 0
        assert c.end_index > c.start_index
        assert len(c.text) > 0
        
        # If it's not the first chunk, it should have a prefix context (since default overlap is 10% / 100 characters)
        if idx > 0:
            assert c.context is not None
            assert len(c.context) > 0
            # The context should match the end of the previous chunk's content
            prev_chunk = chunks[idx - 1]
            assert prev_chunk.text.endswith(c.context)
        else:
            assert c.context is None

def test_env_var_overrides(monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE", "150")
    monkeypatch.setenv("CHUNK_OVERLAP_PCT", "0.20")
    
    sentence = "Governor Gavin Newsom announced a new legislative proposal today regarding California water infrastructure projects. "
    text = sentence * 5
    
    chunks = chunk_article(text)
    
    # Verify that overlap context size matches 20% of 150 (30 characters)
    # and chunk boundaries correspond to smaller chunk size.
    assert len(chunks) > 1
    for c in chunks:
        # With 150 chunk size + 30 context size, max length is 180 characters.
        assert len(c.text) <= 180
        if c.context is not None:
            assert len(c.context) == 30

def test_edge_case_extremely_short_text():
    text = "Hello"
    # Even with 10% overlap context size of 10, overlap is not applied since there is only 1 chunk
    chunks = chunk_article(text, chunk_size=100, chunk_overlap_pct=0.10)
    assert len(chunks) == 1
    assert chunks[0].text == "Hello"
    assert chunks[0].start_index == 0
    assert chunks[0].end_index == 5
    assert chunks[0].context is None
    assert chunks[0].index == 0

def test_edge_case_exact_chunk_size():
    text = "12345"
    chunks = chunk_article(text, chunk_size=5, chunk_overlap_pct=0.20)
    # Since text length fits exactly within chunk_size, it should be 1 chunk
    assert len(chunks) == 1
    assert chunks[0].text == "12345"
    assert chunks[0].start_index == 0
    assert chunks[0].end_index == 5
    assert chunks[0].context is None
    assert chunks[0].index == 0

def test_edge_case_no_spaces():
    text = "abcdefghij" # 10 chars
    # With chunk size 5 and overlap 20% (context size = 1)
    chunks = chunk_article(text, chunk_size=5, chunk_overlap_pct=0.20)
    # The character tokenizer should split this into at least 2 chunks
    assert len(chunks) >= 2
    # Verify that all characters are preserved
    reconstructed = ""
    for idx, c in enumerate(chunks):
        assert len(c.text) > 0
        if idx > 0:
            assert c.context is not None
            # Context size should be 1
            assert len(c.context) == 1
            # Reconstruct text by taking the chunk text without the overlap prefix
            # Since merge=True, the overlap prefix is prepended to the chunk text
            non_overlap = c.text[len(c.context):]
            reconstructed += non_overlap
        else:
            reconstructed += c.text
            
    assert reconstructed == text

def test_invalid_parameters():
    with pytest.raises(ValueError, match="chunk_size must be a positive integer"):
        chunk_article("some text", chunk_size=0)
        
    with pytest.raises(ValueError, match="chunk_size must be a positive integer"):
        chunk_article("some text", chunk_size=-5)
        
    with pytest.raises(ValueError, match="chunk_overlap_pct must be between 0.0 and 0.5"):
        chunk_article("some text", chunk_overlap_pct=-0.1)
        
    with pytest.raises(ValueError, match="chunk_overlap_pct must be between 0.0 and 0.5"):
        chunk_article("some text", chunk_overlap_pct=0.5)
        
    with pytest.raises(ValueError, match="chunk_overlap_pct must be between 0.0 and 0.5"):
        chunk_article("some text", chunk_overlap_pct=1.5)



