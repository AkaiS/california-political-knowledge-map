import pytest
from knowledge_map.utils.chunking import chunk_article
from knowledge_map.schemas import StoryChunk

def test_default_chunking_behavior():
    # A text of about 3000 characters (3x the default chunk size of 1000)
    sentence = "Governor Gavin Newsom announced a new legislative proposal today regarding California water infrastructure projects. "
    text = sentence * 25
    
    chunks = chunk_article(text)
    
    # Check that chunks are returned and are StoryChunk models
    assert len(chunks) > 1
    assert all(isinstance(c, StoryChunk) for c in chunks)
    
    # Check that indices and start/end boundaries align
    for idx, c in enumerate(chunks):
        assert c.index == idx
        assert c.start_index >= 0
        assert c.end_index > c.start_index
        assert len(c.text) > 0
        
        assert c.text == text[c.start_index:c.end_index]

        # If it's not the first chunk, it should have a prefix context (since
        # default overlap is 10% / 100 characters).
        if idx > 0:
            assert c.context is not None
            assert len(c.context) > 0

            context_start = c.start_index - len(c.context)
            assert c.context + c.text == text[context_start:c.end_index]
            assert (
                context_start == 0
                or text[context_start].isspace()
                or text[context_start - 1].isspace()
            )
        else:
            assert c.context is None

def test_config_overrides(monkeypatch):
    from knowledge_map.config import settings
    monkeypatch.setattr(settings.chunking, "size", 150)
    monkeypatch.setattr(settings.chunking, "overlap_pct", 0.20)
    
    sentence = "Governor Gavin Newsom announced a new legislative proposal today regarding California water infrastructure projects. "
    text = sentence * 5
    
    chunks = chunk_article(text)
    
    # Verify that overlap context is at least 20% of 150 (30 characters),
    # allowing the context to extend to the start of its containing word.
    # Chunk text itself remains bounded by the recursive chunk size.
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= 150
        if c.context is not None:
            assert len(c.context) >= 30
            assert c.context + c.text == text[c.start_index - len(c.context):c.end_index]

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
    # The recursive output owns every character exactly once; context is
    # metadata for the following chunk rather than part of its text.
    for idx, c in enumerate(chunks):
        assert len(c.text) > 0
        assert c.text == text[c.start_index:c.end_index]
        if idx > 0:
            assert c.context is not None
            # With no word boundary available, the context expands to the
            # start of the one whitespace-delimited word.
            assert c.context + c.text == text[c.start_index - len(c.context):c.end_index]

    assert "".join(c.text for c in chunks) == text


def test_no_chunk_is_read_starting_in_the_middle_of_a_word():
    # The `ll 623` node existed because a chunk was read starting mid-word,
    # inside `Senate Bill 623`. What has to hold is the general property: what a
    # reader of a chunk sees never begins part-way through a word.
    text = (
        "The Uber ballot measure said Senate Bill 623 would also prohibit the sale "
        "of such liens to drivers and would change the rules for transportation "
        "companies across the state"
    )

    for chunk_size, overlap in ((45, 0.16), (60, 0.2), (120, 0.3)):
        chunks = chunk_article(text, chunk_size=chunk_size, chunk_overlap_pct=overlap)
        for chunk in chunks:
            start = chunk.start_index - len(chunk.context or "")
            assert start == 0 or text[start - 1].isspace() or text[start].isspace(), (
                f"chunk {chunk.index} at size {chunk_size} begins mid-word: "
                f"{chunk.embedded_text[:20]!r}"
            )

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


