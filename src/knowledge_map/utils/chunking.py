from typing import List, Optional
from chonkie import RecursiveChunker, OverlapRefinery
from knowledge_map.schemas import ArticleChunk
from knowledge_map.config import settings


def _snap_context_start_to_word_boundary(text: str, start_index: int) -> int:
    """Move a context start left when it lands inside a whitespace-delimited word."""
    if start_index <= 0 or start_index >= len(text) or text[start_index].isspace():
        return start_index

    while start_index > 0 and not text[start_index - 1].isspace():
        start_index -= 1
    return start_index


def chunk_article(
    text: str,
    chunk_size: Optional[int] = None,
    chunk_overlap_pct: Optional[float] = None
) -> List[ArticleChunk]:
    if chunk_size is None:
        chunk_size = settings.chunking.size
            
    if chunk_overlap_pct is None:
        chunk_overlap_pct = settings.chunking.overlap_pct
            
    if chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    if not (0.0 <= chunk_overlap_pct < .5):
        raise ValueError("chunk_overlap_pct must be between 0.0 and 0.5 (exclusive of 0.5)")
        
    # Initialize recursive chunker
    chunker = RecursiveChunker(
        tokenizer="character",
        chunk_size=chunk_size
    )
    
    # Run chunker
    chunks = chunker.chunk(text)
    
    # Calculate overlap context size
    context_size = int(chunk_size * chunk_overlap_pct)
    
    # Apply OverlapRefinery if context size is positive
    if context_size > 0:
        refinery = OverlapRefinery(
            tokenizer="character",
            context_size=context_size,
            method="prefix",
            mode="token",
            merge=False,
        )
        chunks = refinery.refine(chunks)
        
    # Map to output schema
    article_chunks = []
    for idx, c in enumerate(chunks):
        context = getattr(c, "context", None)
        if context:
            context_start = max(0, c.start_index - len(context))
            context_start = _snap_context_start_to_word_boundary(text, context_start)
            context = text[context_start:c.start_index]

        article_chunks.append(
            ArticleChunk(
                text=c.text,
                start_index=c.start_index,
                end_index=c.end_index,
                index=idx,
                context=context
            )
        )
        
    return article_chunks
