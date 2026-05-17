"""Unit tests for ``scripts.rag.config`` constants (W13-P0).

These tests pin two invariants:

1. The four hybrid weights sum to exactly 1.0 (the hybrid_rank code in
   ``scripts/rag/retrieval/hybrid.py`` requires this for the score to stay
   on ``[0, 1]``).
2. ``WEIGHT_DENSE`` stays demoted (< 0.2) per the W11-I1 ablation finding
   (commit b1e9c8d, ``scripts/rag/evals/ablation_signal_drop.py``) that the
   dense signal at 0.5 was a net-negative contributor to mean_tag_p@5 on
   the 30-scenario eval. Future changes raising it back above 0.2 require
   a fresh ablation showing dense is no longer the dilutor.
"""

from __future__ import annotations

import pytest

from scripts.rag import config


def test_weights_sum_to_one() -> None:
    """The four hybrid ranking weights must sum to exactly 1.0.

    The hybrid_rank function multiplies each signal by its weight and sums;
    if the weights drift off 1.0, the final score breaks its [0, 1] bound
    and downstream consumers (notably the gate bridge) misinterpret it.
    """
    total = (
        config.WEIGHT_DENSE
        + config.WEIGHT_BM25
        + config.WEIGHT_TAG_OVERLAP
        + config.WEIGHT_SEVERITY
    )
    assert total == pytest.approx(1.0, abs=1e-9), (
        f"Hybrid weights must sum to 1.0; got {total!r} "
        f"(dense={config.WEIGHT_DENSE}, bm25={config.WEIGHT_BM25}, "
        f"tag={config.WEIGHT_TAG_OVERLAP}, severity={config.WEIGHT_SEVERITY})"
    )


def test_dense_weight_demoted_per_w11_i1() -> None:
    """WEIGHT_DENSE must stay < 0.2 per W11-I1 ablation finding (W13-P0).

    W11-I1 (commit b1e9c8d) measured on 30 scenarios:
        bm25_only         mean_tag_p@5 = 0.436
        hybrid_all (0.5)  mean_tag_p@5 = 0.353   <-- dense was dilutor
        hybrid_no_dense   mean_tag_p@5 = 0.447

    Raising WEIGHT_DENSE >= 0.2 without a fresh ablation showing dense is
    no longer harmful would undo Wave 13 and re-introduce the regression.
    """
    assert config.WEIGHT_DENSE < 0.2, (
        f"WEIGHT_DENSE={config.WEIGHT_DENSE} >= 0.2 violates the W13-P0 "
        "demotion gate. The W11-I1 ablation (commit b1e9c8d) showed dense "
        "at 0.5 was a net-negative contributor (mean_tag_p@5 0.353 vs "
        "bm25_only 0.436). Run ablation_signal_drop.py before raising."
    )
