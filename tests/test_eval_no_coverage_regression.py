"""W7-P5: guard against A4's ghost-improvement bug.

A4 (Wave 4) noted: if a future change shrinks n_evaluable while
raising mean_hit_at_k, it looks like an improvement but is actually
silent coverage loss.

This test runs run_eval.py against current main and compares coverage_rate
to the committed post-Wave-5 baseline. CI fails if coverage drops >5pp.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
pytest.importorskip("sentence_transformers")

REPO = Path(__file__).resolve().parents[1]
BASELINE = REPO / "references/retrieval_eval/post_wave5_baseline_hybrid.json"
COVERAGE_TOLERANCE = 0.05  # allow 5pp drop before fail


@pytest.mark.slow
def test_coverage_does_not_regress_vs_baseline():
    if not BASELINE.exists():
        pytest.skip("baseline file missing")
    baseline = json.loads(BASELINE.read_text())
    baseline_cov = baseline["aggregate"]["coverage_rate"]

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "current.md"
        r = subprocess.run(
            [sys.executable, "scripts/rag/evals/run_eval.py",
             "--mode", "hybrid", "--output", str(out)],
            capture_output=True, text=True, timeout=300, check=True,
        )
        current = json.loads(out.with_suffix(".json").read_text())
        current_cov = current["aggregate"]["coverage_rate"]

    assert current_cov >= baseline_cov - COVERAGE_TOLERANCE, (
        f"coverage regressed: baseline={baseline_cov:.3f} current={current_cov:.3f} "
        f"tolerance={COVERAGE_TOLERANCE}. This is A4's ghost-improvement guard."
    )
