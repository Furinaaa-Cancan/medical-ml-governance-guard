"""Faithful-replay contract for the BM25 retrieval path gates actually ship (P2.1).

Per RAG_PATH_FINDINGS.md, the published benchmark measured the offline *hybrid*
path while gates ship *BM25* via retrieve_for_failure(gate_name, codes) — and the
old harness even synthesized a query string, which the gate never passes. These
tests lock the shipping path's contract so any future "benchmark" measures what
gates really do:

  * retrieve_for_failure takes only (gate_name, issue_codes[, limit, kb_path]) —
    NO query/query_text param (a synthesized-query regression would break this);
  * it is deterministic (a benchmark over it is reproducible);
  * it returns concerns on the real KB using the exact gate call shape.

The labeled precision@k metric on this path is intentionally left as a flagged
design fork (labeling methodology + the documented self-labeling circularity).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.rag.retrieval.bm25 import retrieve_for_failure  # noqa: E402

# A representative gate failure (the example called out in retrieve_for_failure's
# own docstring), expressed exactly as the gate expresses it.
GATE = "clinical_metrics_gate"
CODES = ["clinical_floor_ppv_not_met"]


def test_shipping_retrieval_takes_no_synthesized_query():
    params = list(inspect.signature(retrieve_for_failure).parameters)
    assert params[:2] == ["gate_name", "issue_codes"]
    # The gate passes ONLY gate_name + codes; a query/query_text param would
    # signal an unfaithful (synthesized-query) retrieval path.
    assert not any("query" in p for p in params)


def test_retrieve_for_failure_is_deterministic():
    a = retrieve_for_failure(GATE, CODES, limit=5)
    b = retrieve_for_failure(GATE, CODES, limit=5)
    assert [r.get("id") for r in a] == [r.get("id") for r in b]


def test_retrieve_for_failure_returns_concerns_on_real_kb():
    results = retrieve_for_failure(GATE, CODES, limit=5)
    assert isinstance(results, list)
    assert len(results) >= 1
    assert all(isinstance(r, dict) for r in results)


def test_limit_is_respected():
    assert len(retrieve_for_failure(GATE, CODES, limit=3)) <= 3
