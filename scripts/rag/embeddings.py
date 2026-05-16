"""Sentence-transformer wrapper for the MLGG RAG layer.

Provides a lazy singleton loader for the configured embedding model and a
batched encoding helper that returns L2-normalized float32 vectors so that
cosine similarity collapses to a dot product downstream.

The model name is read from :mod:`scripts.rag.config` (Agent A1's
file).  If that module is not yet present the loader falls back to the
spec default (``BAAI/bge-small-en-v1.5``) so this module can be imported
and unit-tested in isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sentence_transformers import SentenceTransformer


# Spec defaults, kept in sync with `config.py`.
_DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_DEFAULT_EMBEDDING_DIM = 384
_DEFAULT_BATCH_SIZE = 32

# Module-level singleton handle for the loaded model.
_MODEL: "Optional[SentenceTransformer]" = None


def _resolve_model_name() -> str:
    """Return the embedding model name, preferring the shared RAG config.

    Returns:
        The HuggingFace model id to load.  Falls back to the spec default
        (``BAAI/bge-small-en-v1.5``) if ``scripts.rag.config`` is not
        yet importable (e.g. during Agent A2 standalone testing before
        Agent A1 has landed).
    """

    try:
        from scripts.rag import config  # type: ignore[import-not-found]
    except Exception:
        return _DEFAULT_MODEL_NAME
    return getattr(config, "EMBEDDING_MODEL", _DEFAULT_MODEL_NAME)


def get_model() -> "SentenceTransformer":
    """Lazily load and cache the configured sentence-transformer model.

    The model is loaded on first call (downloading from HuggingFace into
    ``~/.cache/huggingface`` if not already cached, roughly 120 MB for
    ``BAAI/bge-small-en-v1.5``) and reused on every subsequent call.

    Returns:
        The shared :class:`SentenceTransformer` singleton instance.
    """

    global _MODEL
    if _MODEL is None:
        # Imported lazily so importing this module is cheap and avoids the
        # heavy torch/transformers import cost for callers that only need
        # the type stubs.
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer(_resolve_model_name())
    return _MODEL


def embed_texts(
    texts: list[str],
    *,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> np.ndarray:
    """Encode ``texts`` into L2-normalized float32 embeddings.

    The vectors are normalized so that cosine similarity reduces to a
    plain dot product, which keeps the downstream vector-search code
    (Agent A4) trivial and fast.

    Args:
        texts: Input strings to embed.  An empty list returns an empty
            ``(0, EMBEDDING_DIM)`` matrix without loading the model.
        batch_size: Number of texts to encode per forward pass.  Defaults
            to 32 to bound peak memory on large corpora (e.g. the 817
            reviewer concerns) while still amortising the per-call
            overhead.

    Returns:
        A ``(N, EMBEDDING_DIM)`` ``float32`` ``numpy.ndarray`` of unit-norm
        embeddings, where ``N == len(texts)``.

    Raises:
        TypeError: If ``texts`` is not a list of strings.
    """

    if not isinstance(texts, list):
        raise TypeError(
            f"embed_texts expected list[str], got {type(texts).__name__}"
        )
    if texts and not all(isinstance(t, str) for t in texts):
        raise TypeError("embed_texts expected every element to be str")

    if not texts:
        return np.empty((0, _DEFAULT_EMBEDDING_DIM), dtype=np.float32)

    model = get_model()
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    # ``sentence_transformers`` already returns float32 + normalized when
    # asked, but we cast defensively in case a future version changes the
    # default dtype.
    if vectors.dtype != np.float32:
        vectors = vectors.astype(np.float32, copy=False)
    return vectors
