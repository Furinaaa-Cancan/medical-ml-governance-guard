"""Latency / performance regression tests for the RAG layer.

E4 strict-eval measured (post-fix-wave baselines):
  - Warm load: 4.9 ms mean (target <100 ms)
  - Cold build: 15.1 s (target <60 s)
  - Query P50/P95 (steady-state): 12.3 / 31.4 ms
  - First-query latency: ~228 ms (mitigated by prewarm())

This file pins regression budgets. Failing here means someone added
material latency to the hot path — investigate before bypassing.

All tests marked `@pytest.mark.slow` so the default `ci-unit` run
(`-m "not slow"`) skips them; nightly/perf runs pick them up.
"""

from __future__ import annotations

import time
from statistics import median

import pytest

pytest.importorskip("sentence_transformers")


# Generous budgets — measured baseline × ~3 to absorb CI variance.
WARM_LOAD_BUDGET_MS = 300.0       # measured: 4.9 ms
QUERY_P50_BUDGET_MS = 50.0        # measured: 12.3 ms
QUERY_P95_BUDGET_MS = 150.0       # measured: 31.4 ms


@pytest.fixture(scope="module")
def warmed_rag():
    """Force-warm the model + index before timing tests."""
    from scripts.rag import rag_query
    # Drive one query so the model + cache are hot.
    rag_query("calibration", top_k=1)
    return rag_query


@pytest.mark.slow
def test_warm_load_under_budget(warmed_rag) -> None:
    """build_or_load_index() warm path should be <300ms."""
    from scripts.rag.index.builder import build_or_load_index
    samples = []
    for _ in range(5):
        t0 = time.perf_counter()
        build_or_load_index()
        samples.append((time.perf_counter() - t0) * 1000)
    mean_ms = sum(samples) / len(samples)
    assert mean_ms < WARM_LOAD_BUDGET_MS, (
        f"warm load regression: {mean_ms:.1f}ms > {WARM_LOAD_BUDGET_MS}ms budget. "
        f"Samples: {[round(s, 1) for s in samples]}"
    )


@pytest.mark.slow
def test_query_p50_under_budget(warmed_rag) -> None:
    """Steady-state query P50 should be <50ms."""
    queries = [
        "calibration", "leakage", "subgroup analysis", "external validation",
        "missing data", "AUROC confidence interval", "TRIPOD checklist",
        "patient identifier", "class imbalance", "code availability",
    ] * 3  # 30 samples
    latencies = []
    for q in queries:
        t0 = time.perf_counter()
        warmed_rag(q, top_k=5)
        latencies.append((time.perf_counter() - t0) * 1000)
    latencies.sort()
    p50 = median(latencies)
    assert p50 < QUERY_P50_BUDGET_MS, (
        f"query P50 regression: {p50:.1f}ms > {QUERY_P50_BUDGET_MS}ms budget. "
        f"min={latencies[0]:.1f} max={latencies[-1]:.1f}"
    )


@pytest.mark.slow
def test_query_p95_under_budget(warmed_rag) -> None:
    """Steady-state query P95 should be <150ms."""
    queries = [
        "calibration", "leakage", "subgroup analysis", "external validation",
        "missing data", "AUROC confidence interval", "TRIPOD checklist",
        "patient identifier", "class imbalance", "code availability",
    ] * 3
    latencies = []
    for q in queries:
        t0 = time.perf_counter()
        warmed_rag(q, top_k=5)
        latencies.append((time.perf_counter() - t0) * 1000)
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)]
    assert p95 < QUERY_P95_BUDGET_MS, (
        f"query P95 regression: {p95:.1f}ms > {QUERY_P95_BUDGET_MS}ms budget. "
        f"max={latencies[-1]:.1f}"
    )
