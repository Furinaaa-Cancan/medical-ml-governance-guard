"""Smoke test for the committed post-Wave-5 baseline snapshot."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JSON = REPO_ROOT / "references/retrieval_eval/post_wave5_baseline_hybrid.json"
MD = REPO_ROOT / "references/retrieval_eval/post_wave5_baseline_hybrid.md"


def test_baseline_files_exist():
    assert JSON.exists(), f"missing {JSON}"
    assert MD.exists(), f"missing {MD}"


def test_baseline_aggregate_has_primary_metrics():
    d = json.loads(JSON.read_text())
    agg = d["aggregate"]
    # Primary metrics (added by W5 P2)
    assert "mean_hit_at_k" in agg
    assert "coverage_rate" in agg
    # Sanity: hit@K must be in [0, 1]
    assert 0.0 <= agg["mean_hit_at_k"] <= 1.0
    assert 0.0 <= agg["coverage_rate"] <= 1.0
