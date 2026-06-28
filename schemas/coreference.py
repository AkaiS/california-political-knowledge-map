from typing import List
from pydantic import BaseModel, Field

class CriticValidation(BaseModel):
    is_valid: bool = Field(..., description="True if all reference tags are correct and there are no hallucinated or incorrect entities. False if there are issues.")
    issues: List[str] = Field(default_factory=list, description="A list of specific errors or corrections required for incorrect annotations.")
