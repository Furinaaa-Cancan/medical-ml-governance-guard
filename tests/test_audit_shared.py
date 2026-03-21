"""Tests for scripts/_audit_shared.py — shared audit constants and utilities."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _audit_shared import (
    CODE_PATTERNS,
    DIMENSIONS,
    PATTERN_DESCRIPTION,
    PATTERN_SEVERITY,
    QUICK_PATTERN_KEYS,
    check_file_structure,
    load_json_safe,
    scan_code_patterns,
    score_interpretation,
)


# ────────────────────────────────────────────────────────
# score_interpretation
# ────────────────────────────────────────────────────────

class TestScoreInterpretation:
    def test_publication_grade(self):
        assert score_interpretation(100) == ("Publication-grade", "顶刊级")
        assert score_interpretation(90) == ("Publication-grade", "顶刊级")

    def test_solid_but_gaps(self):
        assert score_interpretation(89)[0] == "Solid but gaps remain"
        assert score_interpretation(75)[0] == "Solid but gaps remain"

    def test_major_issues(self):
        assert score_interpretation(74)[0] == "Major issues"
        assert score_interpretation(60)[0] == "Major issues"

    def test_not_publishable(self):
        assert score_interpretation(59)[0] == "Not publishable"
        assert score_interpretation(0)[0] == "Not publishable"

    def test_negative_score(self):
        en, zh = score_interpretation(-5)
        assert en == "Not publishable"
        assert zh == "不可发表"

    def test_boundary_90(self):
        assert score_interpretation(89.999)[0] == "Solid but gaps remain"
        assert score_interpretation(90.0)[0] == "Publication-grade"

    def test_returns_tuple(self):
        result = score_interpretation(50)
        assert isinstance(result, tuple)
        assert len(result) == 2


# ────────────────────────────────────────────────────────
# CODE_PATTERNS registry
# ────────────────────────────────────────────────────────

class TestCodePatterns:
    def test_has_12_patterns(self):
        assert len(CODE_PATTERNS) == 12

    def test_all_patterns_are_compiled_regex(self):
        import re
        for name, pat in CODE_PATTERNS.items():
            assert isinstance(pat, re.Pattern), f"{name} is not a compiled regex"

    def test_quick_pattern_keys_subset(self):
        assert QUICK_PATTERN_KEYS <= set(CODE_PATTERNS.keys())

    def test_quick_pattern_keys_has_6(self):
        assert len(QUICK_PATTERN_KEYS) == 6

    def test_severity_covers_all_patterns(self):
        for name in CODE_PATTERNS:
            assert name in PATTERN_SEVERITY, f"Missing severity for {name}"

    def test_description_covers_all_patterns(self):
        for name in CODE_PATTERNS:
            assert name in PATTERN_DESCRIPTION, f"Missing description for {name}"

    def test_severity_values_valid(self):
        valid = {"CRITICAL", "WARNING", "INFO"}
        for name, sev in PATTERN_SEVERITY.items():
            assert sev in valid, f"{name} has invalid severity {sev}"


# ────────────────────────────────────────────────────────
# Pattern matching accuracy
# ────────────────────────────────────────────────────────

class TestPatternMatching:
    """Verify each regex pattern detects expected code snippets."""

    def test_fit_on_full_data(self):
        pat = CODE_PATTERNS["fit_on_full_data"]
        assert pat.search("scaler.fit(X_all)")
        assert pat.search("model.fit(X_full, y)")
        assert pat.search("pipe.fit(df)")
        assert pat.search("enc.fit(data)")
        assert not pat.search("model.fit(X_train, y_train)")

    def test_test_in_training_loop(self):
        pat = CODE_PATTERNS["test_in_training_loop"]
        assert pat.search("X_test.fit(something)")
        assert pat.search("y_test fit_transform()")
        assert not pat.search("X_train.fit(y)")

    def test_smote_on_full(self):
        pat = CODE_PATTERNS["smote_on_full"]
        assert pat.search("from imblearn import SMOTE")
        assert pat.search("ADASYN()")
        assert pat.search("BorderlineSMOTE()")
        assert not pat.search("some_other_resample()")

    def test_no_random_seed(self):
        pat = CODE_PATTERNS["no_random_seed"]
        assert pat.search("random_state=None")
        assert pat.search("random_state = None")
        assert not pat.search("random_state=42")

    def test_hardcoded_threshold(self):
        pat = CODE_PATTERNS["hardcoded_threshold"]
        assert pat.search("threshold=0.5")
        assert pat.search("threshold = 0.5")
        assert not pat.search("threshold=0.7")

    def test_missing_ci(self):
        pat = CODE_PATTERNS["missing_ci"]
        assert pat.search("accuracy_score = model.score()")
        assert pat.search("auc = 0.85")
        assert pat.search("f1_score = compute_f1()")

    def test_shell_true(self):
        pat = CODE_PATTERNS["shell_true"]
        assert pat.search("subprocess.run(cmd, shell=True)")
        assert pat.search("subprocess.call(cmd, shell = True)")
        assert not pat.search("subprocess.run(cmd)")

    def test_pickle_load_unsafe(self):
        pat = CODE_PATTERNS["pickle_load_unsafe"]
        assert pat.search("pickle.load(f)")
        assert not pat.search("pickle.dump(obj, f)")

    def test_eval_use(self):
        pat = CODE_PATTERNS["eval_use"]
        assert pat.search("eval('1+1')")
        assert not pat.search("evaluate_model()")

    def test_no_train_test_split(self):
        pat = CODE_PATTERNS["no_train_test_split"]
        assert pat.search("train_test_split(X)")
        assert not pat.search("train_test_split(X, y, stratify=y)")

    def test_global_scaler_leak(self):
        pat = CODE_PATTERNS["global_scaler_leak"]
        assert pat.search("StandardScaler()")
        assert pat.search("MinMaxScaler()")
        assert pat.search("RobustScaler()")
        assert not pat.search("CustomScaler()")

    def test_leakage_via_future(self):
        pat = CODE_PATTERNS["leakage_via_future"]
        assert pat.search("discharge_date > today")
        assert pat.search("death_date is not null")
        assert not pat.search("admission_date = '2024-01-01'")


# ────────────────────────────────────────────────────────
# load_json_safe
# ────────────────────────────────────────────────────────

class TestLoadJsonSafe:
    def test_valid_json(self, tmp_path: Path):
        p = tmp_path / "data.json"
        p.write_text('{"key": "value"}', encoding="utf-8")
        result = load_json_safe(p)
        assert result == {"key": "value"}

    def test_missing_file(self, tmp_path: Path):
        assert load_json_safe(tmp_path / "missing.json") is None

    def test_invalid_json(self, tmp_path: Path):
        p = tmp_path / "bad.json"
        p.write_text("{broken", encoding="utf-8")
        assert load_json_safe(p) is None

    def test_non_dict_json(self, tmp_path: Path):
        p = tmp_path / "list.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        # Returns the list as-is (cast to Dict), but should still be non-None
        result = load_json_safe(p)
        # load_json_safe casts, so it returns whatever json.load gives
        assert result is not None

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "empty.json"
        p.write_text("", encoding="utf-8")
        assert load_json_safe(p) is None

    def test_directory_not_file(self, tmp_path: Path):
        assert load_json_safe(tmp_path) is None

    def test_utf8_content(self, tmp_path: Path):
        p = tmp_path / "unicode.json"
        p.write_text('{"中文": "测试"}', encoding="utf-8")
        result = load_json_safe(p)
        assert result == {"中文": "测试"}


# ────────────────────────────────────────────────────────
# scan_code_patterns
# ────────────────────────────────────────────────────────

class TestScanCodePatterns:
    def _make_py_file(self, directory: Path, name: str, content: str) -> Path:
        p = directory / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_detects_fit_on_full(self, tmp_path: Path):
        self._make_py_file(tmp_path, "leaky.py", "scaler.fit(X_all)")
        results = scan_code_patterns(tmp_path)
        assert len(results["fit_on_full_data"]) == 1

    def test_clean_project(self, tmp_path: Path):
        self._make_py_file(tmp_path, "clean.py", "model.fit(X_train, y_train)")
        results = scan_code_patterns(tmp_path)
        assert all(len(v) == 0 for v in results.values())

    def test_multiple_patterns(self, tmp_path: Path):
        code = "scaler.fit(X_all)\nrandom_state=None\nthreshold=0.5"
        self._make_py_file(tmp_path, "multi.py", code)
        results = scan_code_patterns(tmp_path)
        assert len(results["fit_on_full_data"]) == 1
        assert len(results["no_random_seed"]) == 1
        assert len(results["hardcoded_threshold"]) == 1

    def test_quick_subset(self, tmp_path: Path):
        code = "subprocess.run(cmd, shell=True)\nscaler.fit(X_all)"
        self._make_py_file(tmp_path, "mixed.py", code)
        results = scan_code_patterns(tmp_path, pattern_keys=QUICK_PATTERN_KEYS)
        # shell_true not in QUICK_PATTERN_KEYS
        assert "shell_true" not in results
        assert "fit_on_full_data" in results

    def test_file_limit(self, tmp_path: Path):
        for i in range(10):
            self._make_py_file(tmp_path, f"f{i}.py", "scaler.fit(X_all)")
        results = scan_code_patterns(tmp_path, file_limit=3)
        assert len(results["fit_on_full_data"]) <= 3

    def test_ignores_non_py_files(self, tmp_path: Path):
        (tmp_path / "readme.md").write_text("scaler.fit(X_all)")
        results = scan_code_patterns(tmp_path)
        assert all(len(v) == 0 for v in results.values())

    def test_empty_directory(self, tmp_path: Path):
        results = scan_code_patterns(tmp_path)
        assert all(len(v) == 0 for v in results.values())

    def test_relative_paths_in_results(self, tmp_path: Path):
        sub = tmp_path / "src"
        sub.mkdir()
        self._make_py_file(sub, "leaky.py", "scaler.fit(X_all)")
        results = scan_code_patterns(tmp_path)
        for path_str in results["fit_on_full_data"]:
            assert not path_str.startswith("/"), "Should be relative path"

    def test_unreadable_file_skipped(self, tmp_path: Path):
        self._make_py_file(tmp_path, "good.py", "scaler.fit(X_all)")
        bad = tmp_path / "bad.py"
        bad.write_bytes(b"\xff\xfe" + b"\x00" * 100)
        results = scan_code_patterns(tmp_path)
        # Should not crash, and should still find the good file
        assert len(results["fit_on_full_data"]) >= 1


# ────────────────────────────────────────────────────────
# check_file_structure
# ────────────────────────────────────────────────────────

class TestCheckFileStructure:
    def test_empty_directory(self, tmp_path: Path):
        result = check_file_structure(tmp_path)
        assert result["has_train_csv"] is False
        assert result["has_test_csv"] is False
        assert result["has_evidence_dir"] is False
        assert result["has_git"] is False

    def test_full_structure(self, tmp_path: Path):
        (tmp_path / "data_train.csv").touch()
        (tmp_path / "data_valid.csv").touch()
        (tmp_path / "data_test.csv").touch()
        (tmp_path / "request.json").touch()
        (tmp_path / "evidence").mkdir()
        (tmp_path / "model.pkl").touch()
        (tmp_path / "requirements.txt").touch()
        (tmp_path / ".git").mkdir()
        result = check_file_structure(tmp_path)
        assert all(result.values()), f"Not all checks passed: {result}"

    def test_val_csv_variant(self, tmp_path: Path):
        (tmp_path / "data_val.csv").touch()
        result = check_file_structure(tmp_path)
        assert result["has_valid_csv"] is True

    def test_joblib_model(self, tmp_path: Path):
        (tmp_path / "model.joblib").touch()
        result = check_file_structure(tmp_path)
        assert result["has_model_artifact"] is True

    def test_pyproject_as_requirements(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").touch()
        result = check_file_structure(tmp_path)
        assert result["has_requirements"] is True

    def test_nested_csv_found(self, tmp_path: Path):
        sub = tmp_path / "data"
        sub.mkdir()
        (sub / "train_set.csv").touch()
        result = check_file_structure(tmp_path)
        assert result["has_train_csv"] is True

    def test_returns_all_expected_keys(self, tmp_path: Path):
        result = check_file_structure(tmp_path)
        expected_keys = {
            "has_train_csv", "has_valid_csv", "has_test_csv",
            "has_request_json", "has_evidence_dir", "has_model_artifact",
            "has_requirements", "has_git",
        }
        assert set(result.keys()) == expected_keys


# ────────────────────────────────────────────────────────
# DIMENSIONS (12-dimension scoring rubric)
# ────────────────────────────────────────────────────────

class TestDimensions:
    def test_has_12_dimensions(self):
        assert len(DIMENSIONS) == 12

    def test_weights_sum_to_100(self):
        total = sum(d["weight"] for d in DIMENSIONS.values())
        assert total == 100, f"Weights sum to {total}, expected 100"

    def test_ids_are_1_to_12(self):
        ids = sorted(d["id"] for d in DIMENSIONS.values())
        assert ids == list(range(1, 13))

    def test_all_have_required_fields(self):
        for key, dim in DIMENSIONS.items():
            assert "id" in dim, f"{key} missing id"
            assert "name" in dim, f"{key} missing name"
            assert "name_zh" in dim, f"{key} missing name_zh"
            assert "weight" in dim, f"{key} missing weight"

    def test_weights_are_positive(self):
        for key, dim in DIMENSIONS.items():
            assert dim["weight"] > 0, f"{key} has non-positive weight"

    def test_known_dimensions_present(self):
        expected = {
            "data_integrity", "leakage_prevention", "pipeline_isolation",
            "model_selection_rigor", "statistical_validity", "generalization_evidence",
            "clinical_completeness", "reporting_standards", "reproducibility",
            "security_provenance", "fairness_equity", "sample_size_adequacy",
        }
        assert set(DIMENSIONS.keys()) == expected
