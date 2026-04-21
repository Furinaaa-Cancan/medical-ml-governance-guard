"""Tests for UKBCodebook and codebook_factory."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UKB_DB = REPO_ROOT / "references" / "codebooks" / "ukb" / "ukb_codebook.sqlite"
DISEASE_KB = REPO_ROOT / "references" / "methodology" / "disease-definition-knowledge-base.json"
REGISTRY_PATH = REPO_ROOT / "references" / "codebooks" / "dataset-codebook-registry.json"


def _safe_close(cb) -> None:
    """Release SQLite handles held by UKBCodebook/NHANESCodebook instances."""
    if cb is not None and hasattr(cb, "close"):
        cb.close()


# ── parse_ukb_column ───────────────────────────────────────────────

class TestParseUKBColumn:
    """Test UKB column name parsing across all supported formats."""

    def test_rap_format_full(self):
        from scripts.codebooks.ukb_codebook_lookup import parse_ukb_column
        assert parse_ukb_column("p21001_i0_a0") == (21001, 0, 0)

    def test_rap_format_no_array(self):
        from scripts.codebooks.ukb_codebook_lookup import parse_ukb_column
        assert parse_ukb_column("p4080_i1") == (4080, 1, 0)

    def test_rap_format_no_instance_no_array(self):
        from scripts.codebooks.ukb_codebook_lookup import parse_ukb_column
        assert parse_ukb_column("p41270") == (41270, 0, 0)

    def test_showcase_format(self):
        from scripts.codebooks.ukb_codebook_lookup import parse_ukb_column
        assert parse_ukb_column("21001-0.0") == (21001, 0, 0)

    def test_showcase_format_instance1(self):
        from scripts.codebooks.ukb_codebook_lookup import parse_ukb_column
        assert parse_ukb_column("4080-1.0") == (4080, 1, 0)

    def test_bare_field_id(self):
        from scripts.codebooks.ukb_codebook_lookup import parse_ukb_column
        assert parse_ukb_column("21001") == (21001, 0, 0)

    def test_non_ukb_column(self):
        from scripts.codebooks.ukb_codebook_lookup import parse_ukb_column
        assert parse_ukb_column("age") is None

    def test_non_ukb_column_with_underscore(self):
        from scripts.codebooks.ukb_codebook_lookup import parse_ukb_column
        assert parse_ukb_column("blood_pressure") is None


# ── UKBCodebook ────────────────────────────────────────────────────

@pytest.fixture
def ukb_codebook():
    if not UKB_DB.exists():
        pytest.skip("UKB codebook database not found")
    from scripts.codebooks.ukb_codebook_lookup import UKBCodebook
    cb = UKBCodebook(UKB_DB)
    yield cb
    cb.close()


class TestUKBLookup:

    def test_lookup_known_field(self, ukb_codebook):
        info = ukb_codebook.lookup("21001")
        assert info is not None
        assert "bmi" in info["title"].lower() or "body mass" in info["title"].lower()

    def test_lookup_rap_format(self, ukb_codebook):
        info = ukb_codebook.lookup("p30750_i0_a0")
        assert info is not None
        assert info["field_id"] == 30750

    def test_lookup_alias(self, ukb_codebook):
        fid = ukb_codebook.resolve_alias("bmi")
        assert fid == 21001

    def test_lookup_unknown_returns_none(self, ukb_codebook):
        assert ukb_codebook.lookup("9999999") is None

    def test_search_returns_results(self, ukb_codebook):
        results = ukb_codebook.search("blood pressure", limit=5)
        assert len(results) > 0

    def test_variable_count(self, ukb_codebook):
        assert ukb_codebook.variable_count > 0


class TestUKBValidateColumnsForGate:

    def test_outcome_derived_flagged(self, ukb_codebook):
        """Fields from first_occurrence_icd domain should be flagged as outcome."""
        # 131298 = Date I21 first reported (acute MI) — risk_category=outcome_derived
        issues = ukb_codebook.validate_columns_for_gate(
            column_names=["p131298", "p21001_i0_a0"],
            target_col="p2443_i0",
        )
        outcome_issues = [i for i in issues if i["code"] == "CODEBOOK_OUTCOME_AS_FEATURE"]
        assert any(i["details"]["field_id"] == 131298 for i in outcome_issues)
        for i in issues:
            assert {"code", "message", "details"}.issubset(i.keys())

    def test_temporal_leakage_detected(self, ukb_codebook):
        """Feature from instance 2 with target at instance 0 → temporal leakage."""
        issues = ukb_codebook.validate_columns_for_gate(
            column_names=["p21001_i2_a0"],
            target_col="p2443_i0",
        )
        temporal = [i for i in issues if i["code"] == "CODEBOOK_TEMPORAL_LEAKAGE"]
        assert len(temporal) >= 1
        assert temporal[0]["details"]["feature_instance"] == 2
        assert temporal[0]["details"]["target_instance"] == 0

    def test_instance_participation_mnar(self, ukb_codebook):
        """Non-baseline instance with low participation → MNAR warning."""
        issues = ukb_codebook.validate_columns_for_gate(
            column_names=["p21001_i1_a0"],
            target_col="p2443_i0",
        )
        mnar = [i for i in issues if i["code"] == "CODEBOOK_INSTANCE_PARTICIPATION_MNAR"]
        assert len(mnar) >= 1
        assert mnar[0]["details"]["instance"] == 1

    def test_safe_baseline_no_issues(self, ukb_codebook):
        """Baseline features should not be flagged."""
        issues = ukb_codebook.validate_columns_for_gate(
            column_names=["p21001_i0_a0", "p31", "p21022"],
            target_col="p2443_i0",
        )
        critical = [i for i in issues
                     if i["code"] in ("CODEBOOK_OUTCOME_AS_FEATURE",
                                      "CODEBOOK_TEMPORAL_LEAKAGE")]
        assert len(critical) == 0


class TestUKBEncodingCheck:

    def test_categorical_multi_value_flagged(self, ukb_codebook):
        """Categorical field with >2 values should trigger encoding check."""
        issues = ukb_codebook.validate_columns_for_gate(
            column_names=["p21000_i0"],  # Ethnic background, 22 categories
            target_col="p2443_i0",
        )
        encoding = [i for i in issues if i["code"] == "CODEBOOK_ENCODING_CHECK"]
        assert len(encoding) >= 1
        assert encoding[0]["details"]["n_categories"] > 2

    def test_binary_categorical_not_flagged(self, ukb_codebook):
        """Binary categorical (Sex, 2 values) should NOT trigger encoding check."""
        issues = ukb_codebook.validate_columns_for_gate(
            column_names=["p31"],  # Sex (Male/Female)
            target_col="p2443_i0",
        )
        encoding = [i for i in issues if i["code"] == "CODEBOOK_ENCODING_CHECK"]
        assert len(encoding) == 0

    def test_continuous_not_flagged(self, ukb_codebook):
        """Continuous field should NOT trigger encoding check."""
        issues = ukb_codebook.validate_columns_for_gate(
            column_names=["p21001_i0_a0"],  # BMI (continuous)
            target_col="p2443_i0",
        )
        encoding = [i for i in issues if i["code"] == "CODEBOOK_ENCODING_CHECK"]
        assert len(encoding) == 0


class TestUKBSelfReportLeakage:
    """Self-report array fields (20002) containing disease codes → leakage.

    Uses our own UKB encoding_values table (no external dependency).
    """

    def test_self_report_illness_flagged_for_diabetes(self, ukb_codebook):
        if not DISEASE_KB.exists():
            pytest.skip("Disease KB not found")
        issues = ukb_codebook.task_aware_validate(
            column_names=["p20002_i0_a0", "p21001_i0_a0"],
            target_col="p2443_i0",
            target_disease="type_2_diabetes",
            disease_kb_path=str(DISEASE_KB),
        )
        sr = [i for i in issues if i["code"] == "CODEBOOK_SELF_REPORT_LEAKAGE"]
        assert len(sr) == 1
        assert sr[0]["details"]["field_id"] == 20002
        assert sr[0]["details"]["source"] == "ukb_encoding_values"
        # Must contain code 1223 (type 2 diabetes)
        codes = {m["code"] for m in sr[0]["details"]["matching_codes"]}
        assert "1223" in codes

    def test_safe_features_no_self_report_match(self, ukb_codebook):
        if not DISEASE_KB.exists():
            pytest.skip("Disease KB not found")
        issues = ukb_codebook.task_aware_validate(
            column_names=["p21001_i0_a0", "p31"],
            target_col="p2443_i0",
            target_disease="type_2_diabetes",
            disease_kb_path=str(DISEASE_KB),
        )
        sr = [i for i in issues if i["code"] == "CODEBOOK_SELF_REPORT_LEAKAGE"]
        assert len(sr) == 0


class TestUKBTaskAwareValidate:

    def test_diabetes_definition_fields_flagged(self, ukb_codebook):
        if not DISEASE_KB.exists():
            pytest.skip("Disease KB not found")
        issues = ukb_codebook.task_aware_validate(
            column_names=["p30750_i0_a0", "p30740_i0_a0", "p21001_i0_a0"],
            target_col="p2443_i0",
            target_disease="type_2_diabetes",
            disease_kb_path=str(DISEASE_KB),
        )
        flagged_fields = {i["details"]["field_id"] for i in issues}
        assert 30750 in flagged_fields, "HbA1c (30750) should be flagged"
        assert 30740 in flagged_fields, "Glucose (30740) should be flagged"
        assert 21001 not in flagged_fields, "BMI should NOT be flagged"

    def test_safe_features_not_flagged(self, ukb_codebook):
        if not DISEASE_KB.exists():
            pytest.skip("Disease KB not found")
        issues = ukb_codebook.task_aware_validate(
            column_names=["p21001_i0_a0", "p31", "p21022"],
            target_col="p2443_i0",
            target_disease="type_2_diabetes",
            disease_kb_path=str(DISEASE_KB),
        )
        assert len(issues) == 0

    def test_missing_disease_returns_empty(self, ukb_codebook):
        if not DISEASE_KB.exists():
            pytest.skip("Disease KB not found")
        issues = ukb_codebook.task_aware_validate(
            column_names=["p30750_i0_a0"],
            target_disease="nonexistent_disease_xyz",
            disease_kb_path=str(DISEASE_KB),
        )
        assert issues == []


# ── codebook_factory ───────────────────────────────────────────────

class TestCodebookFactory:

    def test_nhanes_returns_codebook(self):
        from scripts.codebooks.codebook_factory import get_codebook
        nhanes_dir = REPO_ROOT / "references" / "codebooks" / "nhanes"
        if not (nhanes_dir / "nhanes_variables.tsv").exists():
            pytest.skip("NHANES TSV not found")
        cb = get_codebook("nhanes")
        try:
            assert cb is not None
            assert cb.variable_count > 0
        finally:
            _safe_close(cb)

    def test_nhanes_cycle_override(self):
        from scripts.codebooks.codebook_factory import get_codebook
        nhanes_dir = REPO_ROOT / "references" / "codebooks" / "nhanes"
        if not (nhanes_dir / "nhanes_variables.tsv").exists():
            pytest.skip("NHANES TSV not found")
        cb = get_codebook("nhanes", nhanes_cycle="2019-2020")
        try:
            assert cb is not None
            assert cb.cycle == "2019-2020"
        finally:
            _safe_close(cb)

    def test_ukb_returns_codebook(self):
        from scripts.codebooks.codebook_factory import get_codebook
        if not UKB_DB.exists():
            pytest.skip("UKB DB not found")
        cb = get_codebook("ukb")
        try:
            assert cb is not None
            assert cb.variable_count > 0
        finally:
            _safe_close(cb)

    def test_ukb_aliases(self):
        from scripts.codebooks.codebook_factory import get_codebook
        if not UKB_DB.exists():
            pytest.skip("UKB DB not found")
        for alias in ("ukbiobank", "biobank"):
            cb = get_codebook(alias)
            try:
                assert cb is not None
            finally:
                _safe_close(cb)

    def test_brfss_returns_registry(self):
        from scripts.codebooks.codebook_factory import get_codebook
        if not REGISTRY_PATH.exists():
            pytest.skip("Registry JSON not found")
        cb = get_codebook("brfss")
        try:
            assert cb is not None
            assert cb.__class__.__name__ == "RegistryCodebook"
        finally:
            _safe_close(cb)

    def test_unknown_source_returns_none(self):
        from scripts.codebooks.codebook_factory import get_codebook
        assert get_codebook("unknown_survey_xyz") is None

    def test_all_codebooks_have_unified_interface(self):
        from scripts.codebooks.codebook_factory import get_codebook
        for source in ("nhanes", "ukb", "brfss"):
            cb = get_codebook(source)
            if cb is None:
                continue
            try:
                assert hasattr(cb, "validate_columns_for_gate")
                assert hasattr(cb, "task_aware_validate")
            finally:
                _safe_close(cb)
            assert hasattr(cb, "variable_count")


# ── manual_registry parity (P1) ──────────────────────────────────────

class TestManualRegistry:
    """Columns listed in manual_registry must be skipped by both entry points."""

    def test_gate_path_respects_manual_registry(self, ukb_codebook):
        # 40000 = Date of death → would normally emit CODEBOOK_OUTCOME_AS_FEATURE
        raw = ukb_codebook.validate_columns_for_gate(["p40000_i0"])
        assert any(i["code"] == "CODEBOOK_OUTCOME_AS_FEATURE" for i in raw)

        overridden = ukb_codebook.validate_columns_for_gate(
            ["p40000_i0"], manual_registry={"p40000_i0": {"reviewed": True}}
        )
        assert all(i["code"] != "CODEBOOK_OUTCOME_AS_FEATURE" for i in overridden)

    def test_task_aware_respects_manual_registry(self, ukb_codebook):
        raw = ukb_codebook.task_aware_validate(
            column_names=["p20002_i0"],
            target_disease="type_2_diabetes",
            disease_kb_path=str(DISEASE_KB),
        )
        assert any(i["code"] == "CODEBOOK_SELF_REPORT_LEAKAGE" for i in raw)

        overridden = ukb_codebook.task_aware_validate(
            column_names=["p20002_i0"],
            target_disease="type_2_diabetes",
            disease_kb_path=str(DISEASE_KB),
            manual_registry={"p20002_i0": {"reviewed": True}},
        )
        assert all(i["code"] != "CODEBOOK_SELF_REPORT_LEAKAGE" for i in overridden)


# ── CLI / gate output unification (P3) ────────────────────────────────

@pytest.mark.skipif(not UKB_DB.exists(), reason="UKB DB not found")
class TestCLIUnifiedCodes:
    """CLI --data output uses the same CODEBOOK_* codes as the gate path."""

    _CLI = REPO_ROOT / "scripts" / "codebooks" / "ukb_codebook_lookup.py"

    def _run_cli(self, columns, report_path):
        import pandas as pd  # local import — only needed for this test
        with tempfile.TemporaryDirectory() as d:
            csv = Path(d) / "x.csv"
            pd.DataFrame(columns=columns).to_csv(csv, index=False)
            return subprocess.run(
                [sys.executable, str(self._CLI),
                 "--data", str(csv), "--report", str(report_path)],
                capture_output=True, text=True,
            )

    def test_death_registry_emits_codebook_prefix_and_exits_critical(self, tmp_path):
        report = tmp_path / "report.json"
        result = self._run_cli(
            ["eid", "p21001_i0", "p40000_i0", "p4080_i0_a0"], report
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "CODEBOOK_OUTCOME_AS_FEATURE" in result.stdout
        assert "UKB_OUTCOME_AS_FEATURE" not in result.stdout

        import json as _json
        payload = _json.loads(report.read_text())
        codes = {i["code"] for i in payload["issues"]}
        assert "CODEBOOK_OUTCOME_AS_FEATURE" in codes
        assert all(c.startswith("CODEBOOK_") for c in codes)
        assert any(i.get("severity") == "critical" for i in payload["issues"])

    def test_safe_columns_exit_zero(self, tmp_path):
        report = tmp_path / "report.json"
        result = self._run_cli(["eid", "p21001_i0", "p4080_i0_a0"], report)
        assert result.returncode == 0, result.stdout + result.stderr
