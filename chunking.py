import os
from typing import List, Optional
from chonkie import RecursiveChunker, OverlapRefinery
from schemas import ArticleChunk

from config import settings

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
