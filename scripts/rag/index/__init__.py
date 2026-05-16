"""RAG embedding-index construction and cache primitives.

Two modules:

  * :mod:`scripts.rag.index.builder` — KB → embedding matrix
    (:func:`build_or_load_index`)
  * :mod:`scripts.rag.index.cache`   — atomic file I/O + sha256-based
    cache invalidation, shared by future cache consumers (BM25 inverted
    index, query results)

Import explicit paths; these modules are NOT re-exported at the package
root.
"""
