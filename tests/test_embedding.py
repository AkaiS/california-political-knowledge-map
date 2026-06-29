import pytest
from unittest.mock import patch
from embedding import cosine_similarity, get_embedding_embedder

def test_cosine_similarity_exact_match():
    v1 = [1.0, 2.0, 3.0]
    v2 = [1.0, 2.0, 3.0]
    assert pytest.approx(cosine_similarity(v1, v2)) == 1.0

def test_cosine_similarity_opposite():
    v1 = [1.0, 0.0]
    v2 = [-1.0, 0.0]
    assert pytest.approx(cosine_similarity(v1, v2)) == -1.0

def test_cosine_similarity_orthogonal():
    v1 = [1.0, 0.0]
    v2 = [0.0, 1.0]
    assert pytest.approx(cosine_similarity(v1, v2)) == 0.0

def test_cosine_similarity_arbitrary():
    v1 = [3.0, 4.0]
    v2 = [4.0, 3.0]
    # Cosine similarity = (3*4 + 4*3) / (sqrt(3^2+4^2) * sqrt(4^2+3^2))
    # = (12+12) / (5 * 5) = 24 / 25 = 0.96
    assert pytest.approx(cosine_similarity(v1, v2)) == 0.96

def test_cosine_similarity_zero_vector():
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0
    assert cosine_similarity([1.0, 2.0], [0.0, 0.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0

def test_cosine_similarity_dimension_mismatch():
    with pytest.raises(ValueError) as exc_info:
        cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])
    assert "Vectors must be of the same dimension" in str(exc_info.value)

def test_get_embedding_embedder():
    import os
    with patch.dict(os.environ, {
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_EMBEDDING_MODEL": "embeddinggemma"
    }):
        embedder = get_embedding_embedder()
        assert embedder is not None
        assert embedder.model.model_name == "embeddinggemma"
