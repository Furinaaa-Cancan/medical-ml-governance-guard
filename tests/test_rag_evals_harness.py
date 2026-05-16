"""Tests for the eval-harness retrieval-path mode flag (W3 finding fix).

W3 (Wave 4, 2026-05-17) exposed that ``scripts/rag/evals/harness.py``
called ``retrieve_for_failure`` directly, measuring BM25-only retrieval
quality. Production users get the ``hybrid_rank`` path
(dense + BM25 + tag overlap + severity + MMR), so every historical
E1 / H14 / W3 P@5 number was evaluating the wrong path.

This file pins:

* ``evaluate_scenario`` default mode is ``"hybrid"`` (production path).
* Both ``hybrid`` and ``bm25_only`` modes still execute end-to-end and
  return per-scenario dicts with the documented metrics shape.
* The CLI exposes ``--mode {bm25_only,hybrid}``.

These tests use the live KB on disk, so they need
``sentence_transformers`` available for the hybrid path; skip otherwise.
"""
from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "rag" / "evals" / "harness.py"

# Canonical scenario shape used by all three end-to-end tests below.
# Mirrors a real scenario in references/retrieval_eval/scenarios.json
# but stays small enough to keep the tests fast.
_CANONICAL_SCENARIO = {
    "scenario_id": "test_calibration_missing",
    "description": "Synthetic scenario for mode-flag smoke test.",
    "gate_name": "calibration_dca_gate",
    "failure_codes": ["MLGG-E02"],
    "expected_categories": ["evaluation_metrics", "calibration"],
    "expected_tags": ["calibration", "ece", "brier"],
    "query_text": "calibration was not assessed in evaluation",
}


def test_harness_defaults_to_hybrid_mode() -> None:
    """Default mode must be 'hybrid' so future evals measure production.

    W3 finding: the legacy bm25_only default was misleading every
    measurement. Default must stay hybrid until rag_query is replaced.
    """
    from scripts.rag.evals.harness import (
        DEFAULT_MODE,
        SUPPORTED_MODES,
        evaluate_scenario,
    )

    assert DEFAULT_MODE == "hybrid", (
        "harness DEFAULT_MODE must be 'hybrid' (production path) — W3 "
        "found that the legacy bm25_only default was measuring the wrong "
        "retrieval stack."
    )
    assert set(SUPPORTED_MODES) == {"bm25_only", "hybrid"}

    sig = inspect.signature(evaluate_scenario)
    assert sig.parameters["mode"].default == "hybrid", (
        "evaluate_scenario(mode=...) default must be 'hybrid'."
    )


def test_harness_rejects_unknown_mode() -> None:
    """An invalid mode must raise rather than silently falling through."""
    from scripts.rag.evals.harness import evaluate_scenario

    with pytest.raises(ValueError, match="mode"):
        evaluate_scenario(_CANONICAL_SCENARIO, mode="not_a_real_mode")


def test_harness_hybrid_mode_runs_end_to_end() -> None:
    """Hybrid mode delegates to rag_query and returns the documented shape."""
    pytest.importorskip("sentence_transformers")
    from scripts.rag.evals.harness import evaluate_scenario

    result = evaluate_scenario(_CANONICAL_SCENARIO, mode="hybrid", top_k=3)

    assert result is not None
    assert result["scenario_id"] == _CANONICAL_SCENARIO["scenario_id"]
    assert result["mode"] == "hybrid"
    # All metrics keys present and in [0, 1].
    for key in ("coverage", "hit_at_k", "tag_precision"):
        assert key in result, f"missing metric {key!r} in hybrid result"
        assert 0.0 <= result[key] <= 1.0, f"{key} out of [0,1]: {result[key]}"
    assert isinstance(result["top_k_summary"], list)
    assert result["retrieved_count"] == len(result["top_k_summary"])


def test_harness_bm25_only_mode_still_works() -> None:
    """bm25_only mode kept for BM25-specific debugging — verify it runs."""
    from scripts.rag.evals.harness import evaluate_scenario

    result = evaluate_scenario(_CANONICAL_SCENARIO, mode="bm25_only", top_k=3)

    assert result is not None
    assert result["mode"] == "bm25_only"
    for key in ("coverage", "hit_at_k", "tag_precision"):
        assert 0.0 <= result[key] <= 1.0


def test_harness_cli_exposes_mode_flag() -> None:
    """``--help`` must advertise --mode with both choices."""
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert r.returncode == 0, r.stderr
    # argparse renders the choices as ``{bm25_only,hybrid}``.
    assert "--mode" in r.stdout
    assert "bm25_only" in r.stdout
    assert "hybrid" in r.stdout
