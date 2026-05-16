"""RAG retrieval evaluation.

Currently one module:

  * :mod:`scripts.rag.evals.harness` — runs a labeled scenario set
    against the live retriever and reports per-scenario coverage + score
    deltas. See ``scripts/rag/evals/harness.py --help``.

Future: scenarios.json fixture set, metrics.py (P@K, MRR, NDCG helpers).

Import explicit paths; not re-exported at the package root.
"""
