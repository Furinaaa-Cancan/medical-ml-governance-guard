"""Dense vector search over the cached MLGG concern embeddings.

This module lives at ``scripts/rag/retrieval/dense.py`` and implements the
``vector_search`` primitive used by the hybrid ranker
(``scripts/rag/_hybrid_ranker.py``). It embeds a free-text query with the
same sentence-transformer model used to build the index, computes cosine
similarity against the pre-normalized concern matrix, and returns the top-K
concern records with a ``_dense_score`` field injected.

Import path: ``from scripts.rag.retrieval.dense import vector_search``.

Design notes:
    * Inputs are assumed to be L2-normalized (the ``_index_builder`` and
      ``embeddings`` modules guarantee this), so cosine similarity reduces to
      a single matrix-vector dot product.
    * For ``top_k < N`` (typical: 50 of 817), ``np.argpartition`` gives an
      O(N) partial selection that is markedly faster than a full ``argsort``.
      We then sort only the K selected indices.
    * Input ``records`` are never mutated; each returned dict is a shallow
      copy with ``_dense_score`` added.

See ``/tmp/mlgg_rag_design.md`` for the full RAG design contract.
"""

from __future__ import annotations

import numpy as np

from scripts.rag.embeddings import embed_texts


def vector_search(
    query: str,
    embeddings: np.ndarray,
    records: list[dict],
    top_k: int = 50,
) -> list[dict]:
    """Return the top-K concern records by cosine similarity to ``query``.

    The ``embeddings`` matrix and the query vector are both produced by
    ``embeddings.embed_texts``, which L2-normalizes its output. Cosine
    similarity therefore equals the plain dot product
    ``embeddings @ query_vec``.

    Args:
        query: Free-text user query (or synthesized failure description).
        embeddings: Pre-normalized concern embeddings of shape
            ``(N, EMBEDDING_DIM)``, aligned by row with ``records``.
        records: Concern dicts of length ``N`` in the same order as
            ``embeddings``. Not mutated.
        top_k: Maximum number of records to return. If ``top_k >= N`` all
            records are returned, sorted by descending score.

    Returns:
        A new ``list[dict]`` of length ``min(top_k, N)``, sorted by
        ``_dense_score`` descending. Each element is a shallow copy of the
        corresponding input record with a ``_dense_score`` float key added.

    Raises:
        ValueError: If ``query`` is empty, ``top_k`` is non-positive, or the
            shapes of ``embeddings`` and ``records`` disagree.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("`query` must be a non-empty string.")
    if top_k <= 0:
        raise ValueError(f"`top_k` must be positive, got {top_k}.")
    if embeddings.ndim != 2:
        raise ValueError(
            f"`embeddings` must be 2-D, got shape {embeddings.shape}."
        )
    if embeddings.shape[0] != len(records):
        raise ValueError(
            "`embeddings` row count "
            f"({embeddings.shape[0]}) must equal len(records) "
            f"({len(records)})."
        )

    n_records: int = embeddings.shape[0]
    if n_records == 0:
        return []

    # Embed the query (shape: (1, EMBEDDING_DIM)) and reduce to a 1-D vector
    # so the dot product yields a 1-D similarity array.
    # BGE-small-en-v1.5 documentation recommends asymmetric encoding:
    # queries get prepended with the instruction below; documents
    # (already encoded by _index_builder.py) are encoded raw. This is worth
    # ~1-2 nDCG points on retrieval tasks per the BAAI paper. The prefix
    # is harmless if the underlying model isn't BGE (it's just a few extra
    # tokens that get encoded into the query vector).
    _QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
    query_vec: np.ndarray = embed_texts([_QUERY_PREFIX + query])[0]

    # Cosine similarity reduces to a dot product because both sides are
    # L2-normalized by the embedding layer.
    scores: np.ndarray = embeddings @ query_vec  # shape: (N,)

    k: int = min(top_k, n_records)

    # Efficient partial selection: O(N) to find the top-k unsorted, then
    # O(k log k) to sort just those k. Much faster than argsort on large N.
    if k < n_records:
        # argpartition with -k puts the k largest at the end (positions
        # [N-k, N)) in arbitrary order.
        partition_idx: np.ndarray = np.argpartition(scores, -k)[-k:]
    else:
        partition_idx = np.arange(n_records)

    # Sort the selected indices by descending score.
    top_indices: np.ndarray = partition_idx[np.argsort(-scores[partition_idx])]

    results: list[dict] = []
    for idx in top_indices:
        idx_int: int = int(idx)
        record_copy: dict = dict(records[idx_int])  # shallow copy
        record_copy["_dense_score"] = float(scores[idx_int])
        results.append(record_copy)

    return results
