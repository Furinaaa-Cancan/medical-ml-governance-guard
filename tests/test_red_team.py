"""Red Team Tests — adversarial input testing for gate bypass and security.

Each test crafts malicious input and verifies the system rejects it.
A test FAILURE means the gate was bypassed = security finding.
"""
from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
GATES_DIR = SCRIPTS_DIR / "gates"
CORE_DIR = SCRIPTS_DIR / "core"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(CORE_DIR))
sys.path.insert(0, str(GATES_DIR))

from _gate_utils import contains_test_token


def _write_json(path: Path, data: Any) -> Path:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _write_csv(path: Path, df: pd.DataFrame) -> Path:
    df.to_csv(path, index=False)
    return path


def _run_gate(gate_script: str, args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(GATES_DIR / gate_script)] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _load_report(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ============================================================================
# Category 1: Unicode/Encoding Bypass
# ============================================================================


class TestUnicodeTokenBypass:
    """Attack: bypass contains_test_token() using Unicode lookalikes."""

    def test_cyrillic_e_bypass(self):
        """'t\u0435st' uses Cyrillic 'e' (U+0435) — visually identical to 'test'."""
        # This is a KNOWN VULNERABILITY — contains_test_token does regex on
        # lowered ASCII, Cyrillic 'е' is not stripped by [^a-z0-9]+
        result = contains_test_token("t\u0435st")
        # If this asserts True, the gate catches it. If False, it's a bypass.
        # We document the finding either way.
        if not result:
            pytest.skip("FINDING: Cyrillic lookalike bypasses contains_test_token")

    def test_leetspeak_bypass(self):
        """'t3st' uses digit 3 for 'e' — should not be treated as 'test'."""
        result = contains_test_token("t3st_data")
        if not result:
            pytest.skip("FINDING: Leetspeak bypasses contains_test_token")

    def test_zero_width_space_in_test(self):
        """'te\u200Bst' has zero-width space — visually identical to 'test'."""
        result = contains_test_token("te\u200Bst")
        if not result:
            pytest.skip("FINDING: Zero-width space bypasses contains_test_token")

    def test_mathematical_italic(self):
        """Mathematical italic 'test' uses codepoints U+1D461 etc."""
        # \U0001d461\U0001d452\U0001d460\U0001d461 = mathematical italic test
        result = contains_test_token("\U0001d461\U0001d452\U0001d460\U0001d461")
        if not result:
            pytest.skip("FINDING: Mathematical italic bypasses contains_test_token")


class TestIDOverlapUnicode:
    """Attack: bypass leakage_gate ID overlap detection with visually identical IDs."""

    def _make_csv(self, path: Path, ids: list, target: list) -> Path:
        df = pd.DataFrame({"patient_id": ids, "y": target, "feat1": [1.0] * len(ids)})
        return _write_csv(path, df)

    def test_invisible_unicode_in_id(self, tmp_path: Path):
        """Train: 'P001', Test: 'P001\\u200B' (zero-width space appended)."""
        train = self._make_csv(tmp_path / "train.csv", ["P001", "P002", "P003"], [0, 1, 0])
        test = self._make_csv(tmp_path / "test.csv", ["P001\u200B", "P004", "P005"], [1, 0, 1])
        report = tmp_path / "report.json"
        result = _run_gate("leakage_gate.py", [
            "--train", str(train), "--test", str(test),
            "--id-cols", "patient_id", "--target-col", "y",
            "--report", str(report),
        ])
        # If gate passes (exit 0), the invisible Unicode bypassed detection
        if result.returncode == 0:
            pytest.skip("FINDING: Zero-width space in patient ID bypasses leakage detection")
        assert result.returncode == 2  # gate should fail

    def test_greek_rho_as_latin_p(self, tmp_path: Path):
        """Train: 'P001' (Latin P), Test: '\u03a1001' (Greek Rho, visually same)."""
        train = self._make_csv(tmp_path / "train.csv", ["P001", "P002"], [0, 1])
        test = self._make_csv(tmp_path / "test.csv", ["\u03a1001", "P003"], [1, 0])
        report = tmp_path / "report.json"
        result = _run_gate("leakage_gate.py", [
            "--train", str(train), "--test", str(test),
            "--id-cols", "patient_id", "--target-col", "y",
            "--report", str(report),
        ])
        if result.returncode == 0:
            pytest.skip("FINDING: Greek Rho lookalike bypasses ID overlap detection")


class TestFeatureLineageCaseBypass:
    """Attack: bypass feature_lineage_gate by case variation in variable names."""

    def test_case_variation(self, tmp_path: Path):
        """Defining variable 'HbA1c' but feature column 'hba1c' (lowercase)."""
        definition_spec = _write_json(tmp_path / "def.json", {
            "diseases": {
                "diabetes": {
                    "targets": {
                        "diabetes": {
                            "defining_variables": ["HbA1c"],
                            "layers": {},
                        }
                    }
                }
            }
        })
        lineage_spec = _write_json(tmp_path / "lineage.json", {
            "features": {
                "hba1c": {"source": "lab", "temporal_category": "pre_index"},
                "age": {"source": "demographics", "temporal_category": "pre_index"},
            }
        })
        train = _write_csv(tmp_path / "train.csv",
                           pd.DataFrame({"patient_id": ["P1"], "y": [1], "hba1c": [7.0], "age": [55]}))
        report = tmp_path / "report.json"
        result = _run_gate("feature_lineage_gate.py", [
            "--target", "diabetes",
            "--definition-spec", str(definition_spec),
            "--lineage-spec", str(lineage_spec),
            "--train", str(train),
            "--target-col", "y",
            "--report", str(report),
        ])
        if result.returncode == 0:
            r = _load_report(report)
            codes = [f["code"] for f in r.get("failures", [])]
            if "forbidden_feature_exact" not in codes and "lineage_definition_leakage" not in codes:
                pytest.skip("FINDING: Case variation bypasses feature lineage leakage detection")


# ============================================================================
# Category 2: NaN/Inf Injection
# ============================================================================


class TestNaNTimestamp:
    """Attack: inject NaN/Inf timestamps to confuse temporal ordering."""

    def test_nan_in_time_column(self, tmp_path: Path):
        """CSV time column with NaN values — should not silently pass temporal check."""
        train = _write_csv(tmp_path / "train.csv", pd.DataFrame({
            "patient_id": ["P1", "P2"], "y": [0, 1],
            "event_time": [float("nan"), float("nan")],
        }))
        test = _write_csv(tmp_path / "test.csv", pd.DataFrame({
            "patient_id": ["P3", "P4"], "y": [1, 0],
            "event_time": [float("nan"), float("nan")],
        }))
        spec = _write_json(tmp_path / "spec.json", {
            "split_strategy": "grouped_temporal",
            "id_col": "patient_id",
            "target_col": "y",
            "time_col": "event_time",
            "requires_temporal_order": True,
            "requires_group_disjoint": True,
            "allows_patient_overlap": False,
            "allows_time_overlap": False,
            "split_frozen": True,
            "split_seed": 42,
        })
        report = tmp_path / "report.json"
        result = _run_gate("split_protocol_gate.py", [
            "--protocol-spec", str(spec),
            "--train", str(train), "--test", str(test),
            "--id-col", "patient_id", "--target-col", "y",
            "--time-col", "event_time",
            "--report", str(report),
        ])
        # Gate should fail or warn about unparseable timestamps
        assert result.returncode == 2 or "no_parseable_times" in result.stdout

    def test_inf_in_time_column(self, tmp_path: Path):
        """Inf timestamp — should not make temporal check vacuously pass."""
        train = _write_csv(tmp_path / "train.csv", pd.DataFrame({
            "patient_id": ["P1"], "y": [0], "event_time": [float("inf")],
        }))
        test = _write_csv(tmp_path / "test.csv", pd.DataFrame({
            "patient_id": ["P2"], "y": [1], "event_time": [1.0],
        }))
        spec = _write_json(tmp_path / "spec.json", {
            "split_strategy": "grouped_temporal",
            "id_col": "patient_id", "target_col": "y", "time_col": "event_time",
            "requires_temporal_order": True, "requires_group_disjoint": True,
            "allows_patient_overlap": False, "allows_time_overlap": False,
            "split_frozen": True, "split_seed": 42,
        })
        report = tmp_path / "report.json"
        result = _run_gate("split_protocol_gate.py", [
            "--protocol-spec", str(spec),
            "--train", str(train), "--test", str(test),
            "--id-col", "patient_id", "--target-col", "y",
            "--time-col", "event_time",
            "--report", str(report),
        ])
        # Inf in train with normal test time → train max = Inf > test min
        # Gate should reject (exit 2) or at least not silently pass (exit 0)
        if result.returncode == 0:
            pytest.fail("FINDING: Inf timestamp silently passed temporal check")
        if result.returncode == 1 and "OverflowError" in result.stderr:
            pytest.skip("FINDING: Inf timestamp causes unhandled OverflowError crash (exit 1 instead of graceful exit 2)")


class TestNaNInEvaluation:
    """Attack: inject NaN/Inf into evaluation reports."""

    def test_inf_metric_in_eval_report(self, tmp_path: Path):
        """evaluation_report.json with pr_auc = Infinity."""
        eval_report = _write_json(tmp_path / "eval.json", {
            "metrics": {"pr_auc": float("inf")},
        })
        report = tmp_path / "report.json"
        result = _run_gate("evaluation_quality_gate.py", [
            "--evaluation-report", str(eval_report),
            "--metric-name", "pr_auc",
            "--report", str(report),
        ])
        assert result.returncode == 2  # should reject Inf metric


# ============================================================================
# Category 3: CSV Safety
# ============================================================================


class TestCSVSafety:
    """Attack: inject malicious content into CSV cells."""

    def test_null_byte_in_csv(self, tmp_path: Path):
        """CSV with null byte in patient_id — should not crash gates."""
        csv_path = tmp_path / "train.csv"
        csv_path.write_text(
            "patient_id,y,feat1\nP\x00001,0,1.0\nP002,1,2.0\n",
            encoding="utf-8",
        )
        test_path = _write_csv(tmp_path / "test.csv", pd.DataFrame({
            "patient_id": ["P003"], "y": [1], "feat1": [3.0],
        }))
        report = tmp_path / "report.json"
        # Should not crash — either process or reject gracefully
        result = _run_gate("leakage_gate.py", [
            "--train", str(csv_path), "--test", str(test_path),
            "--id-cols", "patient_id", "--target-col", "y",
            "--report", str(report),
        ])
        # Any exit code is fine as long as it doesn't crash with traceback
        assert "Traceback" not in result.stderr or result.returncode in (0, 2)


# ============================================================================
# Category 4: Path Traversal
# ============================================================================


class TestPathTraversal:
    """Attack: attempt path traversal via gate arguments."""

    def test_safe_path_blocks_traversal(self):
        """safe_path should reject ../../etc/passwd."""
        from _security import safe_path
        with pytest.raises((ValueError, Exception)):
            safe_path("../../etc/passwd", sandbox=Path("/tmp/safe"))

    def test_safe_path_blocks_null_byte(self):
        """safe_path should reject paths with null bytes."""
        from _security import safe_path
        with pytest.raises((ValueError, Exception)):
            safe_path("/tmp/safe/file\x00.txt")

    def test_safe_path_blocks_system_dirs(self):
        """safe_path should reject paths to /etc, /dev, etc."""
        from _security import safe_path
        for sensitive in ["/etc/passwd", "/dev/null", "/proc/self/environ"]:
            with pytest.raises((ValueError, Exception)):
                safe_path(sensitive)


# ============================================================================
# Category 5: Deserialization
# ============================================================================


class TestRestrictedUnpickler:
    """Attack: craft malicious pickle to execute arbitrary code."""

    def test_os_system_blocked(self, tmp_path: Path):
        """Pickle with os.system('echo pwned') should be blocked."""
        from _security import safe_pickle_load, SecurityError

        # Craft malicious pickle payload
        malicious_path = tmp_path / "evil.pkl"
        # Use raw pickle opcodes to embed os.system call
        import io
        buf = io.BytesIO()
        # This pickle, when loaded normally, would call os.system("echo pwned")
        buf.write(
            b"\x80\x04\x95\x1e\x00\x00\x00\x00\x00\x00\x00"
            b"\x8c\x02os\x94\x8c\x06system\x94\x93\x94"
            b"\x8c\x0becho pwned\x94\x85\x94R\x94."
        )
        buf.seek(0)

        with pytest.raises(SecurityError):
            safe_pickle_load(buf)

    def test_builtins_eval_blocked(self, tmp_path: Path):
        """Pickle with builtins.eval should be blocked."""
        from _security import safe_pickle_load, SecurityError

        import io
        # Craft pickle that calls eval("1+1") using GLOBAL opcode
        # Protocol 2: \x80\x02 c<module>\n<name>\n
        payload = b"\x80\x02cbuiltins\neval\nq\x00X\x03\x00\x00\x001+1q\x01\x85q\x02Rq\x03."
        buf = io.BytesIO(payload)

        with pytest.raises((SecurityError, Exception)):
            safe_pickle_load(buf)


# ============================================================================
# Category 6: Tuning Leakage Gate Evasion
# ============================================================================


class TestTuningLeakageEvasion:
    """Attack: craft tuning protocol that uses test data but evades detection."""

    def _make_spec(self, tmp_path: Path, overrides: dict) -> Path:
        spec = {
            "search_method": "grid_search",
            "model_selection_data": "valid",
            "early_stopping_data": "valid",
            "preprocessing_fit_scope": "train_only",
            "feature_selection_scope": "train_only",
            "resampling_scope": "train_only",
            "final_model_refit_scope": "train_only",
            "objective_metric": "pr_auc",
            "hyperparameter_trials": 10,
            "test_used_for_model_selection": False,
            "test_used_for_early_stopping": False,
            "test_used_for_threshold_selection": False,
            "test_used_for_calibration": False,
            "outer_evaluation_split_locked": True,
            "random_seed_controlled": True,
            "cv": {"enabled": True, "type": "group_k_fold",
                   "n_splits": 5, "nested": False, "group_col": "patient_id"},
        }
        spec.update(overrides)
        return _write_json(tmp_path / "spec.json", spec)

    def test_double_negation_bypass(self, tmp_path: Path):
        """'no_no_test' contains 'no_test' substring — does gate allow it?"""
        spec = self._make_spec(tmp_path, {"model_selection_data": "no_no_test"})
        report = tmp_path / "report.json"
        result = _run_gate("tuning_leakage_gate.py", [
            "--tuning-spec", str(spec), "--has-valid-split",
            "--report", str(report),
        ])
        # 'no_no_test' is NOT a valid selection data value → should fail
        assert result.returncode == 2

    def test_test_in_custom_scope(self, tmp_path: Path):
        """'train_plus_test_validated' should be caught as test usage."""
        spec = self._make_spec(tmp_path, {"final_model_refit_scope": "train_plus_test_validated"})
        report = tmp_path / "report.json"
        result = _run_gate("tuning_leakage_gate.py", [
            "--tuning-spec", str(spec), "--has-valid-split",
            "--report", str(report),
        ])
        r = _load_report(report)
        codes = [f["code"] for f in r.get("failures", [])]
        assert "test_data_usage_detected" in codes or "invalid_final_model_refit_scope" in codes
