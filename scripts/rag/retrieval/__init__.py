"""RAG retrieval signals.

Three modules, one per signal type:

  * :mod:`scripts.rag.retrieval.dense` — sentence-transformer cosine search
  * :mod:`scripts.rag.retrieval.bm25`  — keyword retrieval (gate-anchored)
  * :mod:`scripts.rag.retrieval.hybrid` — 4-signal fusion (the workhorse;
    public via :func:`scripts.rag.rag_query`)

Import explicit paths (e.g. ``from scripts.rag.retrieval.hybrid import
hybrid_rank``); these modules are NOT re-exported at the package root.
"""
