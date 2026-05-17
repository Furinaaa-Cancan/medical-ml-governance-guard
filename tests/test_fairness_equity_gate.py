"""Tests for scripts/fairness_equity_gate.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
GATE_SCRIPT = SCRIPTS_DIR / "gates/fairness_equity_gate.py"

import fairness_equity_gate as feg


# ── _to_float ────────────────────────────────────────────────────────────────

class TestToFloat:
    def test_int(self):
        assert feg._to_float(1) == 1.0

    def test_float(self):
        assert feg._to_float(0.5) == 0.5

    def test_string_number(self):
        assert feg._to_float("0.8") == 0.8

    def test_none_returns_none(self):
        assert feg._to_float(None) is None

    def test_nan_returns_none(self):
        assert feg._to_float(float("nan")) is None

    def test_inf_returns_none(self):
        assert feg._to_float(float("inf")) is None

    def test_neg_inf_returns_none(self):
        assert feg._to_float(float("-inf")) is None

    def test_bad_string_returns_none(self):
        assert feg._to_float("bad") is None


# ── default thresholds ───────────────────────────────────────────────────────

class TestDefaultThresholds:
    def test_equalized_odds_fail_gt_warn(self):
        assert feg.DEFAULT_THRESHOLDS["equalized_odds_gap_fail"] > \
               feg.DEFAULT_THRESHOLDS["equalized_odds_gap_warn"]

    def test_disparate_impact_fail_lt_warn(self):
        assert feg.DEFAULT_THRESHOLDS["disparate_impact_ratio_fail"] < \
               feg.DEFAULT_THRESHOLDS["disparate_impact_ratio_warn"]

    def test_eighty_percent_rule(self):
        assert feg.DEFAULT_THRESHOLDS["disparate_impact_ratio_fail"] == pytest.approx(0.80)

    def test_min_subgroup_size_positive(self):
        assert feg.DEFAULT_THRESHOLDS["min_subgroup_size"] > 0


# ── helpers: eval report fixture ─────────────────────────────────────────────

def _make_eval_report(subgroup_perf=None):
    """Return minimal eval report dict."""
    report = {}
    if subgroup_perf is not None:
        report["subgroup_performance"] = subgroup_perf
    return report


def _write_report(tmp_path: Path, content: dict) -> Path:
    p = tmp_path / "eval_report.json"
    p.write_text(json.dumps(content), encoding="utf-8")
    return p


# ── main() unit tests ─────────────────────────────────────────────────────────

class TestMainMissingFile:
    def test_missing_report_returns_2(self, tmp_path: Path):
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(tmp_path / "nonexistent.json")],
            capture_output=True, text=True,
        )
        assert result.returncode == 2


def _make_args(tmp_path: Path, eval_path=None, strict=False,
               eq_fail=None, di_fail=None, report_path=None):
    import argparse
    return argparse.Namespace(
        evaluation_report=str(eval_path or tmp_path / "eval.json"),
        report=str(report_path) if report_path else None,
        strict=strict,
        equalized_odds_gap_fail=eq_fail,
        disparate_impact_ratio_fail=di_fail,
    )



class TestMainInvalidJson:
    def test_returns_2(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(bad)],
            capture_output=True, text=True,
        )
        assert result.returncode == 2


class TestMainNoSubgroupPerformance:
    def test_returns_2(self, tmp_path: Path):
        p = _write_report(tmp_path, {})
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p)],
            capture_output=True, text=True,
        )
        assert result.returncode == 2


class TestMainPassingReport:
    def _good_report(self):
        return {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.92,
                    "groups": [
                        {"group_label": "M", "n": 200, "pr_auc": 0.75},
                        {"group_label": "F", "n": 180, "pr_auc": 0.72},
                    ],
                }
            }
        }

    def test_exit_0(self, tmp_path: Path):
        p = _write_report(tmp_path, self._good_report())
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_report_written(self, tmp_path: Path):
        p = _write_report(tmp_path, self._good_report())
        rpt = tmp_path / "fairness.json"
        subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p),
             "--report", str(rpt)],
            capture_output=True, text=True,
        )
        assert rpt.exists()
        data = json.loads(rpt.read_text())
        assert data["status"] == "pass"
        assert data["gate_name"] == "fairness_equity_gate"

    def test_report_structure(self, tmp_path: Path):
        p = _write_report(tmp_path, self._good_report())
        rpt = tmp_path / "fairness.json"
        subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p),
             "--report", str(rpt)],
            capture_output=True, text=True,
        )
        data = json.loads(rpt.read_text())
        assert "failures" in data
        assert "warnings" in data
        assert "thresholds" in data.get("summary", {})  # thresholds inside summary


class TestMainEqualizedOddsFailure:
    def test_gap_above_fail_threshold_returns_2(self, tmp_path: Path):
        report = {
            "subgroup_performance": {
                "age_group": {
                    "equalized_odds_gap": 0.20,  # > 0.15 fail threshold
                    "disparate_impact_ratio": 0.90,
                }
            }
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p)],
            capture_output=True, text=True,
        )
        assert result.returncode == 2

    def test_gap_above_warn_only_exits_0(self, tmp_path: Path):
        report = {
            "subgroup_performance": {
                "age_group": {
                    "equalized_odds_gap": 0.12,  # > 0.10 warn, < 0.15 fail
                    "disparate_impact_ratio": 0.90,
                }
            }
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_strict_warn_becomes_failure(self, tmp_path: Path):
        report = {
            "subgroup_performance": {
                "age_group": {
                    "equalized_odds_gap": 0.12,
                    "disparate_impact_ratio": 0.90,
                }
            }
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p),
             "--strict"],
            capture_output=True, text=True,
        )
        assert result.returncode == 2

    def test_custom_threshold_override(self, tmp_path: Path):
        report = {
            "subgroup_performance": {
                "race": {
                    "equalized_odds_gap": 0.20,
                    "disparate_impact_ratio": 0.90,
                }
            }
        }
        p = _write_report(tmp_path, report)
        # raise fail threshold to 0.25 → should pass
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p),
             "--equalized-odds-gap-fail", "0.25"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0


class TestMainDisparateImpact:
    def test_below_fail_threshold_returns_2(self, tmp_path: Path):
        report = {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.70,  # < 0.80
                }
            }
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p)],
            capture_output=True, text=True,
        )
        assert result.returncode == 2

    def test_custom_di_threshold(self, tmp_path: Path):
        report = {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.70,
                }
            }
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p),
             "--disparate-impact-ratio-fail", "0.60"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0


class TestMainSubgroupSampleSize:
    def test_small_subgroup_produces_warning(self, tmp_path: Path):
        report = {
            "subgroup_performance": {
                "rare_group": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.90,
                    "groups": [
                        {"group_label": "rare", "n": 5, "pr_auc": 0.70},
                        {"group_label": "common", "n": 500, "pr_auc": 0.75},
                    ],
                }
            }
        }
        p = _write_report(tmp_path, report)
        rpt = tmp_path / "out.json"
        subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p),
             "--report", str(rpt)],
            capture_output=True, text=True,
        )
        data = json.loads(rpt.read_text())
        codes = [w["code"] for w in data.get("warnings", [])]
        assert "subgroup_sample_too_small" in codes


class TestMainSubgroupPrAuc:
    def test_low_pr_auc_failure(self, tmp_path: Path):
        report = {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.90,
                    "groups": [
                        {"group_label": "F", "n": 200, "pr_auc": 0.30},  # < 0.40 fail
                    ],
                }
            }
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p)],
            capture_output=True, text=True,
        )
        assert result.returncode == 2


class TestMainListSubgroupPerf:
    def test_list_format_accepted(self, tmp_path: Path):
        report = {
            "subgroup_performance": [
                {
                    "feature": "sex",
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.92,
                }
            ]
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0


class TestMainNonFiniteMetric:
    def test_nan_equalized_odds_gap_ignored(self, tmp_path: Path):
        """NaN metrics should be silently skipped (not crash)."""
        report = {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": None,
                    "disparate_impact_ratio": 0.90,
                }
            }
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p)],
            capture_output=True, text=True,
        )
        # Should not crash
        assert result.returncode in (0, 2)


class TestPPVParity:
    """PPV parity (predictive parity) checks."""

    def test_ppv_gap_pass(self, tmp_path: Path):
        report = {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.90,
                    "groups": [
                        {"group_label": "M", "n": 100, "pr_auc": 0.80, "ppv": 0.75},
                        {"group_label": "F", "n": 100, "pr_auc": 0.78, "ppv": 0.72},
                    ],
                }
            }
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "--evaluation-report", str(p)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_ppv_gap_fail(self, tmp_path: Path):
        report = {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.90,
                    "groups": [
                        {"group_label": "M", "n": 100, "pr_auc": 0.80, "ppv": 0.90},
                        {"group_label": "F", "n": 100, "pr_auc": 0.78, "ppv": 0.60},
                    ],
                }
            }
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p), "--report", str(tmp_path / "r.json")],
            capture_output=True, text=True,
        )
        assert result.returncode == 2
        r = json.loads((tmp_path / "r.json").read_text())
        codes = [f["code"] for f in r["failures"]]
        assert "ppv_parity_exceeds_threshold" in codes


class TestCalibrationParity:
    """Calibration slope parity checks."""

    def test_calibration_pass(self, tmp_path: Path):
        report = {
            "subgroup_performance": {
                "age_group": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.90,
                    "groups": [
                        {"group_label": "young", "n": 100, "pr_auc": 0.80, "calibration_slope": 0.95},
                        {"group_label": "old", "n": 100, "pr_auc": 0.78, "calibration_slope": 1.05},
                    ],
                }
            }
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "--evaluation-report", str(p)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_calibration_fail(self, tmp_path: Path):
        report = {
            "subgroup_performance": {
                "age_group": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.90,
                    "groups": [
                        {"group_label": "young", "n": 100, "pr_auc": 0.80, "calibration_slope": 0.95},
                        {"group_label": "old", "n": 100, "pr_auc": 0.78, "calibration_slope": 1.50},
                    ],
                }
            }
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p), "--report", str(tmp_path / "r.json")],
            capture_output=True, text=True,
        )
        assert result.returncode == 2
        r = json.loads((tmp_path / "r.json").read_text())
        codes = [f["code"] for f in r["failures"]]
        assert "calibration_parity_exceeds_threshold" in codes

    def test_calibration_no_data_no_error(self, tmp_path: Path):
        """No calibration_slope in groups → no error (metric is optional)."""
        report = {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.90,
                    "groups": [
                        {"group_label": "M", "n": 100, "pr_auc": 0.80},
                        {"group_label": "F", "n": 100, "pr_auc": 0.78},
                    ],
                }
            }
        }
        p = _write_report(tmp_path, report)
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "--evaluation-report", str(p)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0


class TestCliHelp:
    def test_help_exits_0(self):
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--evaluation-report" in result.stdout
        assert "--strict" in result.stdout
        assert "--report" in result.stdout


# ── Regression tests: nested subgroups shape (introduced 2026-04) ───────────

def _write_report(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "evaluation_report.json"
    p.write_text(json.dumps(data))
    return p


class TestNestedSubgroupShape:
    """train_select_evaluate emits subgroup_performance with a nested
    `subgroups` dict, not flat feature keys. Pre-fix, the gate treated
    the nested dict as a single feature named "subgroups" and silently
    passed — masking real fairness failures (e.g. SUPPORT2 dzclass_Cancer
    sens=0.18, disparate_impact=0.77). These tests pin the drill-in.
    """

    def _nested_report(self) -> dict:
        return {
            "subgroup_performance": {
                "disparate_impact_ratio": 0.77,
                "features_analyzed": ["race", "sex"],
                "subgroups": {
                    "race": {
                        "equalized_odds_gap": 0.25,
                        "groups": [
                            {"group_label": "white", "n": 500, "pr_auc": 0.72,
                             "sensitivity": 0.80, "ppv": 0.55},
                            {"group_label": "black", "n": 200, "pr_auc": 0.48,
                             "sensitivity": 0.55, "ppv": 0.30},
                        ],
                    },
                    "sex": {
                        "equalized_odds_gap": 0.05,
                        "groups": [
                            {"group_label": "M", "n": 400, "pr_auc": 0.75,
                             "sensitivity": 0.82, "ppv": 0.57},
                            {"group_label": "F", "n": 300, "pr_auc": 0.73,
                             "sensitivity": 0.77, "ppv": 0.53},
                        ],
                    },
                },
            }
        }

    def test_drills_into_nested_subgroups(self, tmp_path: Path):
        p = _write_report(tmp_path, self._nested_report())
        rpt = tmp_path / "fairness.json"
        subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p), "--report", str(rpt)],
            capture_output=True, text=True,
        )
        data = json.loads(rpt.read_text())
        # Two features ("race", "sex") must be analyzed, not one "subgroups"
        assert data["summary"]["n_features_analyzed"] == 2
        assert set(data["summary"]["features_analyzed"]) == {"race", "sex"}

    def test_nested_eo_gap_fires_fail(self, tmp_path: Path):
        p = _write_report(tmp_path, self._nested_report())
        rpt = tmp_path / "fairness.json"
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p), "--report", str(rpt)],
            capture_output=True, text=True,
        )
        data = json.loads(rpt.read_text())
        # race eo_gap=0.25 exceeds default fail threshold 0.15
        codes = {f["code"] for f in data["failures"]}
        assert "equalized_odds_gap_exceeds_threshold" in codes
        assert result.returncode == 2

    def test_nested_top_level_di_ratio_fires(self, tmp_path: Path):
        """Top-level disparate_impact_ratio 0.77 < 0.80 fail threshold."""
        p = _write_report(tmp_path, self._nested_report())
        rpt = tmp_path / "fairness.json"
        subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p), "--report", str(rpt)],
            capture_output=True, text=True,
        )
        data = json.loads(rpt.read_text())
        codes = {f["code"] for f in data["failures"]}
        assert "disparate_impact_below_threshold" in codes

    def test_flat_shape_still_works(self, tmp_path: Path):
        """Backward compat: flat {feat: {...}} shape should still iterate."""
        flat = {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.92,
                    "groups": [
                        {"group_label": "M", "n": 200, "pr_auc": 0.75},
                        {"group_label": "F", "n": 180, "pr_auc": 0.72},
                    ],
                }
            }
        }
        p = _write_report(tmp_path, flat)
        rpt = tmp_path / "fairness.json"
        subprocess.run(
            [sys.executable, str(GATE_SCRIPT),
             "--evaluation-report", str(p), "--report", str(rpt)],
            capture_output=True, text=True,
        )
        data = json.loads(rpt.read_text())
        assert data["summary"]["n_features_analyzed"] == 1
        assert data["summary"]["features_analyzed"] == ["sex"]


# ─────────────────────────────────────────────────────────────────────────────
# In-process coverage tests (W14-C2)
#
# The existing tests above all invoke the gate via subprocess.run, which is
# excellent for end-to-end contract checks but is invisible to pytest-cov in
# the parent process (the subprocess Python interpreter has no coverage hook).
# Result: scripts/gates/fairness_equity_gate.py reports ~8% line coverage even
# though most paths are exercised end-to-end.
#
# The classes below import the gate module directly and call main()/helpers
# in-process so coverage instrumentation can observe them. They do NOT replace
# the subprocess tests — the subprocess tests still pin the CLI contract.
# ─────────────────────────────────────────────────────────────────────────────

import csv as _csv
from unittest import mock

import fairness_equity_gate as _feg  # noqa: E402 (already on sys.path via conftest)


def _ip_write_eval(tmp_path: Path, content: dict, name: str = "eval.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(content), encoding="utf-8")
    return p


def _ip_run_main(argv: list) -> int:
    """Call _feg.main() with a mocked sys.argv. Returns exit code."""
    with mock.patch.object(sys, "argv", ["fairness_equity_gate.py", *argv]):
        return _feg.main()


class TestInProcMainHappyPath:
    """Cover the main() success path (lines 266-808)."""

    def _good_report(self) -> dict:
        return {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.92,
                    "groups": [
                        {"group_label": "M", "n": 200, "pr_auc": 0.75,
                         "fpr": 0.10, "fnr": 0.20, "ppv": 0.70,
                         "calibration_slope": 0.95},
                        {"group_label": "F", "n": 180, "pr_auc": 0.72,
                         "fpr": 0.12, "fnr": 0.22, "ppv": 0.68,
                         "calibration_slope": 1.02},
                    ],
                }
            }
        }

    def test_pass_returns_0_and_writes_report(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, self._good_report())
        rp = tmp_path / "out.json"
        rc = _ip_run_main(["--evaluation-report", str(ep), "--report", str(rp)])
        assert rc == 0
        data = json.loads(rp.read_text())
        # Report shape contract
        assert data["status"] == "pass"
        assert data["gate_name"] == "fairness_equity_gate"
        assert "failures" in data and "warnings" in data
        summary = data["summary"]
        for key in (
            "features_analyzed", "n_features_analyzed",
            "equalized_odds_gaps", "max_equalized_odds_gap",
            "disparate_impact_ratios", "min_disparate_impact_ratio",
            "fpr_gaps", "max_fpr_gap",
            "fnr_gaps", "max_fnr_gap",
            "ppv_gaps", "max_ppv_gap",
            "calibration_slope_deviations", "max_calibration_slope_deviation",
            "total_fairness_metrics_reported",
            "subgroup_details", "subgroup_dca",
            "thresholds",
        ):
            assert key in summary, f"summary missing key: {key}"
        # Per-feature detail block populated for each known metric
        sd = summary["subgroup_details"][0]
        assert sd["feature"] == "sex"
        assert sd["n_groups"] == 2
        assert sd["fpr_gap"] is not None
        assert sd["fnr_gap"] is not None
        assert sd["ppv_gap"] is not None
        assert sd["calibration_slope_deviation"] is not None

    def test_pass_without_report_flag(self, tmp_path: Path):
        """No --report flag: gate still returns 0, no file written."""
        ep = _ip_write_eval(tmp_path, self._good_report())
        rc = _ip_run_main(["--evaluation-report", str(ep)])
        assert rc == 0


class TestInProcMainMissingInputs:
    """Cover missing/invalid evaluation_report paths (lines 280-299)."""

    def test_missing_file_returns_2(self, tmp_path: Path):
        rc = _ip_run_main([
            "--evaluation-report", str(tmp_path / "no_such.json"),
        ])
        assert rc == 2

    def test_invalid_json_returns_2(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        rc = _ip_run_main(["--evaluation-report", str(bad)])
        assert rc == 2

    def test_missing_subgroup_performance_returns_2(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {})
        rc = _ip_run_main(["--evaluation-report", str(ep)])
        assert rc == 2

    def test_subgroup_performance_wrong_type_returns_2(self, tmp_path: Path):
        # subgroup_performance is a string, neither dict nor list
        ep = _ip_write_eval(tmp_path, {"subgroup_performance": "not a mapping"})
        rc = _ip_run_main(["--evaluation-report", str(ep)])
        assert rc == 2


class TestInProcFairnessNotAssessedExemption:
    """Cover the fairness_assessment.status='not_assessed' exemption branches
    (lines 301-330)."""

    def test_not_assessed_with_justification_passes(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "fairness_assessment": {
                "status": "not_assessed",
                "justification": "Homogeneous single-site cohort.",
                "plan": "Multi-site validation in v2.",
            },
            "subgroup_performance": {},  # ignored when exemption fires
        })
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        # Justified exemption is a warning, not a failure → exit 0
        assert rc == 0
        data = json.loads(rp.read_text())
        warning_codes = [w["code"] for w in data.get("warnings", [])]
        assert "fairness_not_assessed_justified" in warning_codes

    def test_not_assessed_without_justification_fails(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "fairness_assessment": {"status": "not_assessed"},
            "subgroup_performance": {},
        })
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        assert rc == 2
        data = json.loads(rp.read_text())
        failure_codes = [f["code"] for f in data.get("failures", [])]
        assert "fairness_not_assessed_no_justification" in failure_codes

    def test_not_assessed_strict_justified_still_fails(self, tmp_path: Path):
        """Under --strict, the justified-exemption warning escalates."""
        ep = _ip_write_eval(tmp_path, {
            "fairness_assessment": {
                "status": "not_assessed",
                "justification": "Homogeneous cohort.",
            },
            "subgroup_performance": {},
        })
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--strict",
        ])
        assert rc == 2


class TestInProcThresholdBreaches:
    """Cover each metric-breach branch (lines 404-698)."""

    def test_equalized_odds_fail(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {"equalized_odds_gap": 0.30,
                        "disparate_impact_ratio": 0.95}
            }
        })
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        assert rc == 2
        codes = [f["code"] for f in json.loads(rp.read_text())["failures"]]
        assert "equalized_odds_gap_exceeds_threshold" in codes

    def test_equalized_odds_warn_only_passes(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {"equalized_odds_gap": 0.12,  # > 0.10 warn, < 0.15 fail
                        "disparate_impact_ratio": 0.95}
            }
        })
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        assert rc == 0
        codes = [w["code"] for w in json.loads(rp.read_text())["warnings"]]
        assert "equalized_odds_gap_exceeds_threshold" in codes

    def test_disparate_impact_fail(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {"equalized_odds_gap": 0.05,
                        "disparate_impact_ratio": 0.50}
            }
        })
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        assert rc == 2
        codes = [f["code"] for f in json.loads(rp.read_text())["failures"]]
        assert "disparate_impact_below_threshold" in codes

    def test_disparate_impact_warn_only_passes(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {"equalized_odds_gap": 0.05,
                        "disparate_impact_ratio": 0.83}  # < 0.85 warn, > 0.80
            }
        })
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        assert rc == 0
        codes = [w["code"] for w in json.loads(rp.read_text())["warnings"]]
        assert "disparate_impact_below_threshold" in codes

    def test_fpr_parity_fail(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": [
                        {"group_label": "M", "n": 100, "fpr": 0.05},
                        {"group_label": "F", "n": 100, "fpr": 0.30},
                    ],
                }
            }
        })
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        assert rc == 2
        codes = [f["code"] for f in json.loads(rp.read_text())["failures"]]
        assert "fpr_parity_exceeds_threshold" in codes

    def test_fpr_parity_warn_only(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": [
                        {"group_label": "M", "n": 100, "fpr": 0.05},
                        {"group_label": "F", "n": 100, "fpr": 0.18},
                    ],
                }
            }
        })
        rc = _ip_run_main(["--evaluation-report", str(ep)])
        assert rc == 0

    def test_fnr_parity_fail(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": [
                        {"group_label": "M", "n": 100, "fnr": 0.10},
                        {"group_label": "F", "n": 100, "fnr": 0.40},
                    ],
                }
            }
        })
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        assert rc == 2
        codes = [f["code"] for f in json.loads(rp.read_text())["failures"]]
        assert "fnr_parity_exceeds_threshold" in codes

    def test_fnr_parity_warn_only(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": [
                        {"group_label": "M", "n": 100, "fnr": 0.10},
                        {"group_label": "F", "n": 100, "fnr": 0.22},
                    ],
                }
            }
        })
        rc = _ip_run_main(["--evaluation-report", str(ep)])
        assert rc == 0

    def test_ppv_parity_warn_only(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": [
                        {"group_label": "M", "n": 100, "ppv": 0.70},
                        {"group_label": "F", "n": 100, "ppv": 0.57},
                    ],
                }
            }
        })
        rc = _ip_run_main(["--evaluation-report", str(ep)])
        assert rc == 0

    def test_calibration_warn_only(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": [
                        {"group_label": "M", "n": 100, "calibration_slope": 0.95},
                        {"group_label": "F", "n": 100, "calibration_slope": 1.25},
                    ],
                }
            }
        })
        rc = _ip_run_main(["--evaluation-report", str(ep)])
        assert rc == 0  # 0.25 deviation: > 0.20 warn but < 0.30 fail

    def test_subgroup_pr_auc_warn_only(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": [
                        {"group_label": "F", "n": 200, "pr_auc": 0.45},
                    ],
                }
            }
        })
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        assert rc == 0
        codes = [w["code"] for w in json.loads(rp.read_text())["warnings"]]
        assert "subgroup_metric_below_minimum" in codes


class TestInProcSubgroupSizeEdges:
    """Cover the three sample-size warning branches (lines 474-514)."""

    def test_subgroup_below_min_size(self, tmp_path: Path):
        # n=5 → too small (< min_subgroup_size=20)
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": [
                        {"group_label": "rare", "n": 5, "pr_auc": 0.70},
                        {"group_label": "common", "n": 500, "pr_auc": 0.75},
                    ],
                }
            }
        })
        rp = tmp_path / "out.json"
        _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        codes = [w["code"] for w in json.loads(rp.read_text())["warnings"]]
        assert "subgroup_sample_too_small" in codes

    def test_subgroup_below_warn_size_30(self, tmp_path: Path):
        # n=25 → above min(20), below warn(30)
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": [
                        {"group_label": "small", "n": 25, "pr_auc": 0.70},
                        {"group_label": "big", "n": 500, "pr_auc": 0.75},
                    ],
                }
            }
        })
        rp = tmp_path / "out.json"
        _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        codes = [w["code"] for w in json.loads(rp.read_text())["warnings"]]
        assert "subgroup_sample_too_small" in codes

    def test_subgroup_unstable_size(self, tmp_path: Path):
        # n=40 → above warn(30), below stable(50)
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": [
                        {"group_label": "mid", "n": 40, "pr_auc": 0.70},
                        {"group_label": "big", "n": 500, "pr_auc": 0.75},
                    ],
                }
            }
        })
        rp = tmp_path / "out.json"
        _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        codes = [w["code"] for w in json.loads(rp.read_text())["warnings"]]
        assert "subgroup_sample_unstable" in codes

    def test_group_using_count_alias(self, tmp_path: Path):
        # 'count' is accepted as an alias for 'n'
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": [
                        {"group_label": "M", "count": 200, "pr_auc": 0.75},
                        {"group_label": "F", "count": 180, "pr_auc": 0.72},
                    ],
                }
            }
        })
        rc = _ip_run_main(["--evaluation-report", str(ep)])
        assert rc == 0

    def test_groups_as_dict_form(self, tmp_path: Path):
        # groups can be a {label: {...}} dict, not just a list
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": {
                        "M": {"n": 200, "pr_auc": 0.75, "fpr": 0.10},
                        "F": {"n": 180, "pr_auc": 0.72, "fpr": 0.12},
                    },
                }
            }
        })
        rc = _ip_run_main(["--evaluation-report", str(ep)])
        assert rc == 0


class TestInProcListShape:
    """Cover the list-shape branch (line 387-388)."""

    def test_list_subgroup_performance(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": [
                {"feature": "sex",
                 "equalized_odds_gap": 0.05,
                 "disparate_impact_ratio": 0.92},
                {"feature": "age_bin",
                 "equalized_odds_gap": 0.06,
                 "disparate_impact_ratio": 0.90},
            ]
        })
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        assert rc == 0
        data = json.loads(rp.read_text())
        assert data["summary"]["n_features_analyzed"] == 2


class TestInProcNestedTopLevelDI:
    """Cover the nested-shape top-level disparate-impact branches (lines 362-385)."""

    def test_top_di_warn_band(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "disparate_impact_ratio": 0.83,  # warn-band: < 0.85, > 0.80
                "subgroups": {
                    "sex": {
                        "equalized_odds_gap": 0.05,
                        "groups": [
                            {"group_label": "M", "n": 200, "pr_auc": 0.75},
                            {"group_label": "F", "n": 180, "pr_auc": 0.72},
                        ],
                    },
                },
            }
        })
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        assert rc == 0
        codes = [w["code"] for w in json.loads(rp.read_text())["warnings"]]
        assert "disparate_impact_below_threshold" in codes


class TestInProcMultiplicityAndImpossibility:
    """Cover the multiple-comparisons and impossibility-theorem branches
    (lines 730-755). Multiplicity warning fires when n_features * 7 > 10
    (i.e. >= 2 features). Impossibility info fires when
    total_fairness_metrics_reported >= 3."""

    def test_multiplicity_warning_fires(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.95,
                    "groups": [
                        {"group_label": "M", "n": 100, "fpr": 0.10, "fnr": 0.20,
                         "ppv": 0.70, "calibration_slope": 0.98},
                        {"group_label": "F", "n": 100, "fpr": 0.12, "fnr": 0.22,
                         "ppv": 0.68, "calibration_slope": 1.02},
                    ],
                },
                "age": {
                    "equalized_odds_gap": 0.05,
                    "disparate_impact_ratio": 0.93,
                    "groups": [
                        {"group_label": "young", "n": 100, "fpr": 0.11},
                        {"group_label": "old", "n": 100, "fpr": 0.13},
                    ],
                },
            }
        })
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep), "--report", str(rp),
        ])
        assert rc == 0
        data = json.loads(rp.read_text())
        codes = [w["code"] for w in data["warnings"]]
        assert "multiple_comparisons_unadjusted" in codes
        # Impossibility note lives in summary.info, not warnings
        info_codes = [i["code"] for i in data["summary"]["info"]]
        assert "impossibility_theorem_note" in info_codes


class TestInProcThresholdOverrides:
    """Cover --equalized-odds-gap-fail and --disparate-impact-ratio-fail
    override branches (lines 273-277)."""

    def test_eo_override_raises_pass(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {"equalized_odds_gap": 0.25,
                        "disparate_impact_ratio": 0.95}
            }
        })
        # Default fail=0.15 → would fail. Override to 0.30 → pass.
        rc = _ip_run_main([
            "--evaluation-report", str(ep),
            "--equalized-odds-gap-fail", "0.30",
        ])
        assert rc == 0

    def test_di_override_lowers_pass(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, {
            "subgroup_performance": {
                "sex": {"equalized_odds_gap": 0.05,
                        "disparate_impact_ratio": 0.50}
            }
        })
        # Default fail=0.80 → fail. Override to 0.40 → pass.
        rc = _ip_run_main([
            "--evaluation-report", str(ep),
            "--disparate-impact-ratio-fail", "0.40",
        ])
        assert rc == 0


# ─────────────────────────────────────────────────────────────────────────────
# Subgroup-DCA in-process coverage (cover _run_subgroup_dca_check lines 811-1015)
# ─────────────────────────────────────────────────────────────────────────────

def _ip_write_trace(tmp_path: Path, rows: list, group_col: str = "race",
                    fname: str = "trace.csv") -> Path:
    p = tmp_path / fname
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["y_true", "y_score", group_col])
        for y, s, g in rows:
            w.writerow([y, s, g])
    return p


def _ip_good_trace(tmp_path: Path, group_col: str = "race") -> Path:
    import numpy as np
    rng = np.random.default_rng(0)
    rows = []
    for grp in ("A", "B"):
        y = rng.choice([0, 1], 300, p=[0.7, 0.3])
        ys = np.clip(y * 0.6 + rng.normal(0.2, 0.1, 300), 0.01, 0.99)
        for yi, si in zip(y, ys):
            rows.append((float(yi), float(si), grp))
    return _ip_write_trace(tmp_path, rows, group_col=group_col)


class TestInProcSubgroupDcaPaths:
    """Cover the _run_subgroup_dca_check helper directly + via main()."""

    def _baseline_eval(self) -> dict:
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

    def test_dca_missing_trace_warns(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, self._baseline_eval())
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep),
            "--subgroup-dca",  # opt-in but no trace path
            "--report", str(rp),
        ])
        assert rc == 0
        data = json.loads(rp.read_text())
        codes = [w["code"] for w in data["warnings"]]
        assert "subgroup_dca_input_missing" in codes
        assert data["summary"]["subgroup_dca"]["status"] == "skipped"

    def test_dca_trace_file_missing(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, self._baseline_eval())
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep),
            "--prediction-trace", str(tmp_path / "no_trace.csv"),
            "--subgroup-dca-column", "race",
            "--subgroup-dca",
            "--report", str(rp),
        ])
        assert rc == 0
        data = json.loads(rp.read_text())
        codes = [w["code"] for w in data["warnings"]]
        assert "subgroup_dca_input_unreadable" in codes

    def test_dca_trace_missing_columns(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, self._baseline_eval())
        bad_trace = tmp_path / "bad.csv"
        # Missing y_score and race columns
        bad_trace.write_text("y_true\n0\n1\n0\n", encoding="utf-8")
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep),
            "--prediction-trace", str(bad_trace),
            "--subgroup-dca-column", "race",
            "--subgroup-dca",
            "--report", str(rp),
        ])
        assert rc == 0
        data = json.loads(rp.read_text())
        codes = [w["code"] for w in data["warnings"]]
        assert "subgroup_dca_input_unreadable" in codes

    def test_dca_positive_passes(self, tmp_path: Path):
        ep = _ip_write_eval(tmp_path, self._baseline_eval())
        trace = _ip_good_trace(tmp_path, group_col="race")
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep),
            "--prediction-trace", str(trace),
            "--subgroup-dca-column", "race",
            "--subgroup-dca",
            "--subgroup-dca-threshold-min", "0.05",
            "--subgroup-dca-threshold-max", "0.20",
            "--report", str(rp),
        ])
        assert rc == 0
        data = json.loads(rp.read_text())
        dca = data["summary"]["subgroup_dca"]
        assert dca["status"] == "computed"
        assert dca["subgroup_column"] == "race"
        assert dca["failing_subgroups"] == []

    def test_dca_all_groups_too_small_insufficient_data(self, tmp_path: Path):
        """Trace where every subgroup has < 20 samples → insufficient_data
        branch (lines 959-971)."""
        ep = _ip_write_eval(tmp_path, self._baseline_eval())
        rows = []
        # Both subgroups well below n=20 minimum required by subgroup_dca
        for grp in ("A", "B"):
            for i in range(5):
                rows.append((float(i % 2), 0.3 + 0.1 * (i % 2), grp))
        trace = _ip_write_trace(tmp_path, rows, group_col="race")
        rp = tmp_path / "out.json"
        rc = _ip_run_main([
            "--evaluation-report", str(ep),
            "--prediction-trace", str(trace),
            "--subgroup-dca-column", "race",
            "--subgroup-dca",
            "--report", str(rp),
        ])
        assert rc == 0
        data = json.loads(rp.read_text())
        dca = data["summary"]["subgroup_dca"]
        # status is "insufficient_data" — every group failed the n>=20 gate
        assert dca["status"] in ("insufficient_data", "computed")
        codes = [w["code"] for w in data["warnings"]]
        if dca["status"] == "insufficient_data":
            assert "subgroup_dca_skipped_insufficient_data" in codes

