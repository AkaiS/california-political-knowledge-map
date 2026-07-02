from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class ArticleSelectors(BaseModel):
    title: str
    author: str
    date: str
    body: str

class SelectorVersion(BaseModel):
    id: Optional[int] = None
    publication_id: str
    selectors: ArticleSelectors
    earliest_success_date: datetime
    latest_success_date: datetime
    created_at: Optional[datetime] = None
