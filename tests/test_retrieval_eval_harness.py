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
BASELINE_HYBRID = (
    REPO_ROOT / "references" / "retrieval_eval" / "baseline_hybrid.json"
)
# Scenario IDs that are deliberate off-domain / empty-query probes — they
# are *expected* to miss (coverage=hit@K=0). They must be excluded from
# per-scenario floor assertions but kept in the aggregate so the harness
# still reports the long-tail behaviour honestly.
OFF_DOMAIN_PROBE_IDS = {
    "weak_offdomain_music_query",
    "weak_offdomain_sailing_query",
    "weak_offdomain_woodworking_query",
    "zero_empty_query",
}
# Scenarios that are known tag-miss in the legacy bm25_only baseline
# (kept in the canonical scenarios.json so the aggregate stays honest,
# but excluded from --strict per-scenario hit@K=1.0 enforcement).
BM25_KNOWN_TAG_MISS_IDS = {
    "robustness_no_perturbation_test",
}


def _run(*args: str):
    # 60s timeout: hybrid mode cold-loads the BGE model (~20s) before
    # running the 30-scenario sweep, leaving little headroom under the
    # historical 30s budget on slower CI runners.
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=60,
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

    @staticmethod
    def _on_topic_scenarios_file(
        tmp_path: Path, extra_excludes: set | None = None
    ) -> Path:
        """Write a scenarios.json into ``tmp_path`` containing only
        on-topic scenarios — i.e. all scenarios *except* the
        deliberate off-domain / empty-query probes (and any
        ``extra_excludes`` for mode-specific known misses). The
        harness's ``--strict`` mode hard-fails on any hit@K=0, so
        scenarios that are *meant* to miss (or are known baseline
        tag-misses) must be filtered out here.
        """
        full = json.loads(SCENARIOS.read_text())
        excludes = OFF_DOMAIN_PROBE_IDS | (extra_excludes or set())
        filtered = {
            **full,
            "scenarios": [
                s for s in full["scenarios"]
                if s["scenario_id"] not in excludes
            ],
        }
        path = tmp_path / "scenarios_on_topic.json"
        path.write_text(json.dumps(filtered))
        return path

    @pytest.mark.skipif(not BASELINE.exists(),
                        reason="Retrieval baseline not yet captured")
    def test_strict_against_baseline(self, tmp_path: Path):
        """Strict regression check in the legacy ``bm25_only`` mode.

        ``baseline.json`` is the historical bm25_only snapshot — that
        is what every published P@5 number was measured against, so
        keep it as the legacy regression guard. The hybrid production
        path has its own baseline file checked below.
        """
        report = tmp_path / "r.json"
        scenarios = self._on_topic_scenarios_file(
            tmp_path, extra_excludes=BM25_KNOWN_TAG_MISS_IDS,
        )
        r = _run(
            "--mode", "bm25_only",
            "--scenarios", str(scenarios),
            "--baseline", str(BASELINE),
            "--report", str(report),
            "--strict",
        )
        assert r.returncode == 0, (
            "Retrieval regressed vs baseline — run "
            "scripts/rag/evals/harness.py --mode bm25_only --verbose "
            "for details.\n"
            + r.stdout + r.stderr
        )
        data = json.loads(report.read_text())
        # Sanity: every on-topic scenario landed at least one
        # on-topic concern.
        for s in data["scenarios"]:
            assert s["coverage"] >= 1.0, (
                f"scenario {s['scenario_id']} lost category coverage"
            )

    @pytest.mark.skipif(not BASELINE_HYBRID.exists(),
                        reason="Hybrid retrieval baseline not yet captured")
    def test_strict_against_baseline_hybrid(self, tmp_path: Path):
        """Strict regression check in the production ``hybrid`` mode.

        ``baseline_hybrid.json`` snapshots the dense+BM25+tag+severity
        path that real users hit through ``rag_query``. This is the
        path that matters for end-user retrieval quality.
        """
        report = tmp_path / "r.json"
        scenarios = self._on_topic_scenarios_file(tmp_path)
        r = _run(
            "--mode", "hybrid",
            "--scenarios", str(scenarios),
            "--baseline", str(BASELINE_HYBRID),
            "--report", str(report),
            "--strict",
        )
        assert r.returncode == 0, (
            "Hybrid retrieval regressed vs baseline — run "
            "scripts/rag/evals/harness.py --mode hybrid --verbose "
            "for details.\n"
            + r.stdout + r.stderr
        )
        data = json.loads(report.read_text())
        for s in data["scenarios"]:
            assert s["coverage"] >= 1.0, (
                f"scenario {s['scenario_id']} lost category coverage"
            )
            assert s["hit_at_k"] >= 1.0, (
                f"scenario {s['scenario_id']} lost hit@K"
            )

    def test_baseline_aggregate_floor(self, tmp_path: Path):
        """Catastrophic-drift guard.

        Floors are deliberately generous so future small KB / synonym
        rewordings don't false-positive. They are computed from the
        canonical scenarios.json which mixes on-topic + off-domain
        probes; the off-domain probes drag the aggregate down by
        design (we *want* the harness to honestly report misses on
        unrelated queries), so the floors sit well below the on-topic
        sub-population mean.

        Current baselines (2026-05-17, 30 scenarios, hybrid default):
          coverage_rate=0.867  hit_at_k_rate=0.867  mean_tag_p=0.338
        bm25_only legacy snapshot:
          coverage_rate=0.867  hit_at_k_rate=0.833  mean_tag_p=0.436
        """
        report = tmp_path / "r.json"
        r = _run("--scenarios", str(SCENARIOS), "--report", str(report))
        assert r.returncode == 0
        data = json.loads(report.read_text())
        agg = data["aggregate"]
        assert agg["coverage_rate"] >= 0.80, agg
        assert agg["hit_at_k_rate"] >= 0.80, agg
        assert agg["mean_tag_precision"] >= 0.30, (
            f"mean_tag_precision dropped to {agg['mean_tag_precision']} — "
            "inspect with scripts/rag/evals/harness.py --verbose"
        )
