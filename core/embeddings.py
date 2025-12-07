"""
Pattern Project - Embeddings Module
Lazy-loaded sentence transformers for vector embeddings
"""

import threading
from typing import Optional, List, Union
import numpy as np

from core.logger import log_loading_start, log_loading_complete, log_info, log_error

# Type hints for sentence_transformers (lazy import)
SentenceTransformer = None

# Global model instance
_model = None
_model_lock = threading.Lock()
_model_name: str = ""
_embedding_dimensions: int = 0


def load_embedding_model(model_name: str = "all-MiniLM-L6-v2") -> bool:
    """
    Load the embedding model. This is lazy-loaded to avoid startup delays.

    Args:
        model_name: Name of the sentence-transformers model to load

    Returns:
        True if successful, False otherwise
    """
    global _model, _model_name, _embedding_dimensions, SentenceTransformer

    with _model_lock:
        if _model is not None:
            return True

        try:
            log_loading_start("EMBEDDING MODEL")

            log_info(f"Importing sentence_transformers library...", prefix="📦")

            # Lazy import to avoid startup delay
            from sentence_transformers import SentenceTransformer as ST
            SentenceTransformer = ST

            log_info(f"Loading model ({model_name})...", prefix="📦")

            _model = SentenceTransformer(model_name)
            _model_name = model_name

            # Get embedding dimensions by encoding a test string
            test_embedding = _model.encode("test", convert_to_numpy=True)
            _embedding_dimensions = len(test_embedding)

            log_loading_complete("Embedding model", f"{_embedding_dimensions} dimensions")

            return True

        except Exception as e:
            error_msg = str(e)
            log_error(f"Failed to load embedding model: {error_msg}")

            # Provide Windows-specific troubleshooting for DLL errors
            if "WinError 1114" in error_msg or "DLL" in error_msg:
                log_error("")
                log_error("=" * 60)
                log_error("WINDOWS DLL ERROR - Common with Microsoft Store Python")
                log_error("=" * 60)
                log_error("Try these solutions:")
                log_error("")
                log_error("1. Install Visual C++ Redistributable:")
                log_error("   https://aka.ms/vs/17/release/vc_redist.x64.exe")
                log_error("")
                log_error("2. Use standard Python instead of Microsoft Store version:")
                log_error("   https://www.python.org/downloads/")
                log_error("")
                log_error("3. Try CPU-only PyTorch:")
                log_error("   pip uninstall torch")
                log_error("   pip install torch --index-url https://download.pytorch.org/whl/cpu")
                log_error("")
                log_error("=" * 60)

            return False


def get_embedding(text: str) -> Optional[np.ndarray]:
    """
    Get the embedding vector for a text string.

    Args:
        text: The text to embed

    Returns:
        numpy array of the embedding, or None if model not loaded
    """
    with _model_lock:
        if _model is None:
            log_error("Embedding model not loaded. Call load_embedding_model() first.")
            return None

        try:
            embedding = _model.encode(text, convert_to_numpy=True)
            return embedding.astype(np.float32)
        except Exception as e:
            log_error(f"Failed to generate embedding: {e}")
            return None


def get_embeddings_batch(texts: List[str]) -> Optional[np.ndarray]:
    """
    Get embedding vectors for multiple texts (more efficient than individual calls).

    Args:
        texts: List of texts to embed

    Returns:
        numpy array of shape (len(texts), embedding_dim), or None if failed
    """
    with _model_lock:
        if _model is None:
            log_error("Embedding model not loaded. Call load_embedding_model() first.")
            return None

        if not texts:
            return np.array([])

        try:
            embeddings = _model.encode(texts, convert_to_numpy=True)
            return embeddings.astype(np.float32)
        except Exception as e:
            log_error(f"Failed to generate batch embeddings: {e}")
            return None


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """
    Calculate cosine similarity between two vectors.

    Args:
        vec1: First embedding vector
        vec2: Second embedding vector

    Returns:
        Cosine similarity score (0 to 1)
    """
    dot_product = np.dot(vec1, vec2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return float(dot_product / (norm1 * norm2))


def cosine_similarity_batch(query_vec: np.ndarray, vectors: np.ndarray) -> np.ndarray:
    """
    Calculate cosine similarity between a query vector and multiple vectors.

    Args:
        query_vec: Query embedding vector (1D)
        vectors: Matrix of vectors to compare against (2D: n_vectors x embedding_dim)

    Returns:
        Array of similarity scores
    """
    if len(vectors) == 0:
        return np.array([])

    # Normalize query
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return np.zeros(len(vectors))
    query_normalized = query_vec / query_norm

    # Normalize all vectors
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1  # Avoid division by zero
    vectors_normalized = vectors / norms

    # Compute all similarities at once
    similarities = np.dot(vectors_normalized, query_normalized)

    return similarities


def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    """Convert embedding numpy array to bytes for database storage."""
    return embedding.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes, dimensions: int = 384) -> np.ndarray:
    """Convert bytes from database back to numpy array."""
    return np.frombuffer(data, dtype=np.float32).reshape(dimensions)


def is_model_loaded() -> bool:
    """Check if the embedding model is loaded."""
    with _model_lock:
        return _model is not None


def get_model_info() -> dict:
    """Get information about the loaded model."""
    with _model_lock:
        return {
            "loaded": _model is not None,
            "model_name": _model_name,
            "dimensions": _embedding_dimensions
        }
