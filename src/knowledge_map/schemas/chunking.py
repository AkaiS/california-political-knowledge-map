from typing import Optional
from pydantic import BaseModel

class StoryChunk(BaseModel):
    text: str
    start_index: int
    end_index: int
    index: int
    context: Optional[str] = None

    @property
    def embedded_text(self) -> str:
        """The chunk as retrieval consumes it: its overlap context, then its text.

        Read by everything that retrieves.  Extraction reads ``text`` alone, so
        an entity named in the overlap is extracted once.
        """
        return (self.context or "") + self.text


# Deprecated alias for backward compatibility; use StoryChunk.
ArticleChunk = StoryChunk
