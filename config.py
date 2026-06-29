from pydantic import BaseModel, Field

class ChunkingSettings(BaseModel):
    size: int = Field(default=1000, description="Default chunk size (characters/tokens)")
    overlap_pct: float = Field(default=0.10, description="Overlap percentage as decimal")

class EmbeddingSettings(BaseModel):
    dimension: int = Field(default=768, description="Vector dimension size for Neo4j index")

class Settings(BaseModel):
    chunking: ChunkingSettings = ChunkingSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()

settings = Settings()
