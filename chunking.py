import os
from typing import List, Optional
from pydantic import BaseModel
from chonkie import RecursiveChunker, OverlapRefinery

# Safe defaults
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP_PCT = 0.10

class ArticleChunk(BaseModel):
    text: str
    start_index: int
    end_index: int
    index: int
    context: Optional[str] = None

def chunk_article(
    text: str,
    chunk_size: Optional[int] = None,
    chunk_overlap_pct: Optional[float] = None
) -> List[ArticleChunk]:
    if chunk_size is None:
        env_chunk_size = os.environ.get("CHUNK_SIZE")
        if env_chunk_size is not None:
            chunk_size = int(env_chunk_size)
        else:
            chunk_size = DEFAULT_CHUNK_SIZE
            
    if chunk_overlap_pct is None:
        env_overlap = os.environ.get("CHUNK_OVERLAP_PCT")
        if env_overlap is not None:
            chunk_overlap_pct = float(env_overlap)
        else:
            chunk_overlap_pct = DEFAULT_CHUNK_OVERLAP_PCT
            
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
            mode="token"
        )
        chunks = refinery.refine(chunks)
        
    # Map to output schema
    article_chunks = []
    for idx, c in enumerate(chunks):
        article_chunks.append(
            ArticleChunk(
                text=c.text,
                start_index=c.start_index,
                end_index=c.end_index,
                index=idx,
                context=getattr(c, "context", None)
            )
        )
        
    return article_chunks
