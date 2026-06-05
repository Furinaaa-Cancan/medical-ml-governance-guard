"""Tests for the subgroup-DCA wiring in fairness_equity_gate.

W13-T0: subgroup_dca was previously library-only (defined in
scripts/core/_gate_utils.py but invoked by no gate). This test module
verifies the new opt-in / strict-auto wiring in fairness_equity_gate.

Test plan:
  - test_subgroup_dca_opt_in_default_off
  - test_subgroup_dca_opt_in_flag_on
  - test_strict_mode_includes_subgroup_dca
  - test_subgroup_dca_passes_when_all_subgroups_positive
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
GATE_SCRIPT = SCRIPTS_DIR / "gates/fairness_equity_gate.py"


# ── shared fixtures ─────────────────────────────────────────────────────────

def _baseline_eval_report() -> dict:
    """An eval report that passes all the non-DCA fairness checks.

    All subgroup-level metrics fall well inside warn thresholds so any
    test failure is unambiguously attributable to subgroup-DCA wiring.
    """
    return {
        "subgroup_performance": {
            "sex": {
                "equalized_odds_gap": 0.04,
                "disparate_impact_ratio": 0.95,
                "groups": [
                    {"group_label": "M", "n": 200, "pr_auc": 0.78},
                    {"group_label": "F", "n": 200, "pr_auc": 0.76},
                ],
            }
        }
    }


def _write_eval_report(tmp_path: Path, content: dict) -> Path:
    p = tmp_path / "eval_report.json"
    p.write_text(json.dumps(content), encoding="utf-8")
    return p


def _write_trace(tmp_path: Path, rows: List[Tuple[float, float, str]],
                 fname: str = "prediction_trace.csv",
                 group_col: str = "race") -> Path:
    """Write a minimal y_true,y_score,<group_col> CSV."""
    p = tmp_path / fname
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["y_true", "y_score", group_col])
        for y, s, g in rows:
            w.writerow([y, s, g])
    return p


def _good_trace(tmp_path: Path, seed: int = 0, n: int = 300,
                group_col: str = "race") -> Path:
    """Two subgroups, both with a model that has positive net benefit."""
    rng = np.random.default_rng(seed)
    rows: List[Tuple[float, float, str]] = []
    for grp in ("A", "B"):
        y = rng.choice([0, 1], n, p=[0.7, 0.3])
        # y_score correlated with y so net benefit > 0 in the 0.05–0.20 band
        ys = np.clip(y * 0.6 + rng.normal(0.2, 0.1, n), 0.01, 0.99)
        for yi, si in zip(y, ys):
            rows.append((float(yi), float(si), grp))
    return _write_trace(tmp_path, rows, group_col=group_col)


def _harmful_trace(tmp_path: Path, group_col: str = "race") -> Path:
    """One subgroup with negative net benefit (degenerate predictor).

    Group A: model has decent predictive value (NB > 0).
    Group B: model outputs ~0.95 for every patient but prevalence is ~5%
             — almost all positives are false positives, net benefit < 0
             across the clinically-relevant 0.05–0.20 threshold band.
    """
    rng = np.random.default_rng(0)
    n_a, n_b = 200, 200
    rows: List[Tuple[float, float, str]] = []

    y_a = rng.choice([0, 1], n_a, p=[0.7, 0.3])
    ys_a = np.clip(y_a * 0.6 + rng.normal(0.2, 0.1, n_a), 0.01, 0.99)
    for yi, si in zip(y_a, ys_a):
        rows.append((float(yi), float(si), "A"))

    y_b = rng.choice([0, 1], n_b, p=[0.95, 0.05])
    ys_b = np.full(n_b, 0.95)
    for yi, si in zip(y_b, ys_b):
        rows.append((float(yi), float(si), "B"))

    return _write_trace(tmp_path, rows, group_col=group_col)


def _run_gate(*cli_args: str, expect_returncode: int = None,
              env_extra: dict = None):
    """Helper: run the gate CLI and return CompletedProcess."""
    proc = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), *cli_args],
        capture_output=True, text=True,
    )
    if expect_returncode is not None:
        assert proc.returncode == expect_returncode, (
            f"expected rc={expect_returncode} got {proc.returncode}\n"
            f"stdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}"
        )
    return proc


# ── Deliverable 2.1: opt-in default OFF ─────────────────────────────────────

class TestSubgroupDCAOptInDefaultOff:
    """Without --subgroup-dca (and without --strict), the check must NOT
    run. Existing CI baselines that don't supply a prediction trace must
    keep passing untouched.
    """

    def test_default_no_subgroup_dca_block_in_summary(self, tmp_path: Path):
        eval_path = _write_eval_report(tmp_path, _baseline_eval_report())
        report_path = tmp_path / "out.json"

        _run_gate(
            "--evaluation-report", str(eval_path),
            "--report", str(report_path),
            expect_returncode=0,
        )

        data = json.loads(report_path.read_text())
        summary = data.get("summary", {})
        # When not requested, subgroup_dca block is None (not "computed")
        assert summary.get("subgroup_dca") is None, (
            "subgroup_dca block should be absent when neither --subgroup-dca "
            "nor --strict is passed"
        )

    def test_default_no_subgroup_dca_warnings_or_failures(self, tmp_path: Path):
        eval_path = _write_eval_report(tmp_path, _baseline_eval_report())
        report_path = tmp_path / "out.json"

        _run_gate(
            "--evaluation-report", str(eval_path),
            "--report", str(report_path),
            expect_returncode=0,
        )

        data = json.loads(report_path.read_text())
        all_codes = [
            i["code"] for i in
            data.get("failures", []) + data.get("warnings", [])
        ]
        # None of the subgroup-DCA codes should appear when opt-in is off
        dca_codes = {
            "fairness_subgroup_dca_negative",
            "subgroup_dca_input_missing",
            "subgroup_dca_input_unreadable",
            "subgroup_dca_skipped_insufficient_data",
        }
        leaked = dca_codes & set(all_codes)
        assert not leaked, f"unexpected DCA-related codes when off: {leaked}"


# ── Deliverable 2.2: opt-in flag ON, harmful subgroup → FAIL ────────────────

class TestSubgroupDCAOptInFlagOn:
    """With --subgroup-dca, the gate invokes subgroup_dca and FAILs when
    a subgroup has negative net benefit at clinically-relevant thresholds.
    """

    def test_flag_on_negative_nb_subgroup_fails_gate(self, tmp_path: Path):
        eval_path = _write_eval_report(tmp_path, _baseline_eval_report())
        trace_path = _harmful_trace(tmp_path, group_col="race")
        report_path = tmp_path / "out.json"

        proc = _run_gate(
            "--evaluation-report", str(eval_path),
            "--prediction-trace", str(trace_path),
            "--subgroup-dca-column", "race",
            "--subgroup-dca",
            "--report", str(report_path),
            expect_returncode=2,
        )

        data = json.loads(report_path.read_text())
        failure_codes = [f["code"] for f in data.get("failures", [])]
        assert "fairness_subgroup_dca_negative" in failure_codes, (
            f"expected fairness_subgroup_dca_negative in failures, "
            f"got {failure_codes}; stderr={proc.stderr}"
        )

        # Report summary must record the per-group net benefit and the
        # failing subgroups so reviewers can audit the decision.
        dca = data["summary"]["subgroup_dca"]
        assert dca["status"] == "computed"
        assert dca["subgroup_column"] == "race"
        assert "B" in [g["group"] for g in dca["failing_subgroups"]]

    def test_inverted_threshold_band_skips_with_warning(self, tmp_path: Path):
        # min > max must be rejected (it would build a non-monotonic grid and
        # produce a meaningless verdict) — skip + warn, not silently proceed.
        eval_path = _write_eval_report(tmp_path, _baseline_eval_report())
        trace_path = _good_trace(tmp_path, group_col="race")
        report_path = tmp_path / "out.json"
        _run_gate(
            "--evaluation-report", str(eval_path),
            "--prediction-trace", str(trace_path),
            "--subgroup-dca-column", "race",
            "--subgroup-dca",
            "--subgroup-dca-threshold-min", "0.30",
            "--subgroup-dca-threshold-max", "0.05",
            "--report", str(report_path),
            expect_returncode=0,  # warn + skip, not a failure
        )
        data = json.loads(report_path.read_text())
        dca = data["summary"]["subgroup_dca"]
        assert dca["status"] == "skipped"
        assert dca.get("reason") == "threshold_band_inverted"
        warn_codes = [w["code"] for w in data.get("warnings", [])]
        assert "subgroup_dca_threshold_order_invalid" in warn_codes

    def test_flag_on_missing_trace_warns_not_fails(self, tmp_path: Path):
        """Opt-in without supplying inputs should warn (not fail) outside
        strict mode — keeps the gate friendly to incremental adoption."""
        eval_path = _write_eval_report(tmp_path, _baseline_eval_report())
        report_path = tmp_path / "out.json"

        _run_gate(
            "--evaluation-report", str(eval_path),
            "--subgroup-dca",  # opt-in but no trace
            "--report", str(report_path),
            expect_returncode=0,  # warn-only, gate still passes
        )

        data = json.loads(report_path.read_text())
        warning_codes = [w["code"] for w in data.get("warnings", [])]
        assert "subgroup_dca_input_missing" in warning_codes


# ── Deliverable 2.3: strict mode auto-includes the check ────────────────────

class TestStrictModeIncludesSubgroupDCA:
    """When --strict is set, subgroup_dca runs even without --subgroup-dca.
    This is the publication-grade contract: strict callers don't need to
    remember the extra flag.
    """

    def test_strict_auto_runs_subgroup_dca_and_fails_on_harm(self, tmp_path: Path):
        eval_path = _write_eval_report(tmp_path, _baseline_eval_report())
        trace_path = _harmful_trace(tmp_path, group_col="race")
        report_path = tmp_path / "out.json"

        _run_gate(
            "--evaluation-report", str(eval_path),
            "--prediction-trace", str(trace_path),
            "--subgroup-dca-column", "race",
            "--strict",  # auto-includes subgroup_dca without explicit flag
            "--report", str(report_path),
            expect_returncode=2,
        )

        data = json.loads(report_path.read_text())
        failure_codes = [f["code"] for f in data.get("failures", [])]
        assert "fairness_subgroup_dca_negative" in failure_codes
        dca = data["summary"]["subgroup_dca"]
        assert dca["status"] == "computed"


# ── Deliverable 2.4: positive net benefit → PASS ────────────────────────────

class TestSubgroupDCAPositive:
    """When every subgroup has positive net benefit across the threshold
    band, the gate passes and reports computed per-group net benefits.
    """

    def test_all_subgroups_positive_passes(self, tmp_path: Path):
        eval_path = _write_eval_report(tmp_path, _baseline_eval_report())
        trace_path = _good_trace(tmp_path, group_col="race")
        report_path = tmp_path / "out.json"

        _run_gate(
            "--evaluation-report", str(eval_path),
            "--prediction-trace", str(trace_path),
            "--subgroup-dca-column", "race",
            "--subgroup-dca",
            "--report", str(report_path),
            expect_returncode=0,
        )

        data = json.loads(report_path.read_text())
        failure_codes = [f["code"] for f in data.get("failures", [])]
        assert "fairness_subgroup_dca_negative" not in failure_codes

        dca = data["summary"]["subgroup_dca"]
        assert dca["status"] == "computed"
        # Both A and B should have positive optimal net benefit
        nbs = dca["group_optimal_net_benefit"]
        assert all(v > 0 for v in nbs.values()), (
            f"expected all groups > 0 net benefit, got {nbs}"
        )
        assert dca["failing_subgroups"] == []
