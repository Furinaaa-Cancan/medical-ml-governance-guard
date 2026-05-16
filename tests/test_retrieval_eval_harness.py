"""Tests for scripts/rag/evals/harness.py.

Also runs the harness against the live KB + baseline as a CI regression
guard — if KB changes tank retrieval quality, these fail loudly.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "rag" / "evals" / "harness.py"
SCENARIOS = REPO_ROOT / "references" / "retrieval_eval" / "scenarios.json"
BASELINE = REPO_ROOT / "references" / "retrieval_eval" / "baseline.json"


def _run(*args: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=30,
    )


class TestHarnessBasics:
    def test_scenarios_file_shape(self):
        data = json.loads(SCENARIOS.read_text())
        assert "scenarios" in data and len(data["scenarios"]) >= 3
        for s in data["scenarios"]:
            for key in ("scenario_id", "gate_name",
                        "failure_codes", "expected_categories", "expected_tags"):
                assert key in s, f"scenario {s} missing {key}"

    def test_missing_scenarios_file_exits_nonzero(self, tmp_path: Path):
        r = _run("--scenarios", str(tmp_path / "nope.json"))
        assert r.returncode == 2

    def test_empty_scenarios_exits_nonzero(self, tmp_path: Path):
        f = tmp_path / "empty.json"
        f.write_text(json.dumps({"scenarios": []}))
        r = _run("--scenarios", str(f))
        assert r.returncode == 2


class TestLiveRetrievalQuality:
    """CI regression guard. Before merging any change that touches
    the KB, the retrieval module, or synonym table, these must stay
    at baseline-or-better. If a scenario drops below its baseline
    coverage/hit@K, or tag_precision falls by >0.05, the CI fails."""

    @pytest.mark.skipif(not BASELINE.exists(),
                        reason="Retrieval baseline not yet captured")
    def test_strict_against_baseline(self, tmp_path: Path):
        report = tmp_path / "r.json"
        r = _run(
            "--scenarios", str(SCENARIOS),
            "--baseline", str(BASELINE),
            "--report", str(report),
            "--strict",
        )
        assert r.returncode == 0, (
            "Retrieval regressed vs baseline — run "
            "scripts/rag/evals/harness.py --verbose "
            "for details.\n"
            + r.stdout + r.stderr
        )
        data = json.loads(report.read_text())
        # Sanity: every scenario landed at least one on-topic concern.
        for s in data["scenarios"]:
            assert s["coverage"] >= 1.0, (
                f"scenario {s['scenario_id']} lost category coverage"
            )
            assert s["hit_at_k"] >= 1.0, (
                f"scenario {s['scenario_id']} lost hit@K"
            )

    def test_baseline_aggregate_floor(self, tmp_path: Path):
        """If the baseline drifts catastrophically (e.g., someone
        rewrites the synonym table without re-baselining), this
        catches it. Hard floor: mean_tag_precision must stay ≥ 0.4
        across the seed scenarios."""
        report = tmp_path / "r.json"
        r = _run("--scenarios", str(SCENARIOS), "--report", str(report))
        assert r.returncode == 0
        data = json.loads(report.read_text())
        agg = data["aggregate"]
        assert agg["coverage_rate"] >= 1.0, agg
        assert agg["hit_at_k_rate"] >= 1.0, agg
        assert agg["mean_tag_precision"] >= 0.4, (
            f"mean_tag_precision dropped to {agg['mean_tag_precision']} — "
            "inspect with scripts/rag/evals/harness.py --verbose"
        )
