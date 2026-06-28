from typing import Optional
from pydantic import BaseModel

class ArticleChunk(BaseModel):
    text: str
    start_index: int
    end_index: int
    index: int
    context: Optional[str] = None
