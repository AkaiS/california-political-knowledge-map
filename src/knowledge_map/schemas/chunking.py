from typing import Optional
from pydantic import BaseModel

class ArticleChunk(BaseModel):
    text: str
    start_index: int
    end_index: int
    index: int
    context: Optional[str] = None

    @property
    def embedded_text(self) -> str:
        """The chunk as retrieval consumes it: its overlap context, then its text.

        Extraction reads ``text`` alone so an entity named in the overlap is
        extracted once, from the chunk that owns it. Everything that retrieves
        reads this instead, so the overlap is retained.
        """
        return (self.context or "") + self.text
