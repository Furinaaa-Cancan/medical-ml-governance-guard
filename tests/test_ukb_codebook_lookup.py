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


# ── RAP field-list generation ──────────────────────────────────────

class TestFieldToRAPNames:
    """Test RAP column-name expansion — the actual output RAP consumes."""

    def test_not_instanced_not_arrayed(self, ukb_codebook):
        # Field 31 (Sex): instanced=0, arrayed=0 → single "p31"
        names = ukb_codebook.field_to_rap_names(31)
        assert names == ["p31"]

    def test_instanced_not_arrayed(self, ukb_codebook):
        # Field 21001 (BMI): instanced>0, arrayed=0 → "p21001_i0"
        assert ukb_codebook.field_to_rap_names(21001, instance=0) == ["p21001_i0"]
        assert ukb_codebook.field_to_rap_names(21001, instance=2) == ["p21001_i2"]

    def test_instanced_and_arrayed_expands(self, ukb_codebook):
        # Field 4080 (Systolic BP): instanced>0, arrayed>0 (2 measurements)
        names = ukb_codebook.field_to_rap_names(4080, instance=0)
        assert names[0] == "p4080_i0_a0"
        assert all(n.startswith("p4080_i0_a") for n in names)
        assert len(names) >= 2

    def test_categorical_multiple_not_array_expanded(self, ukb_codebook):
        # Field 20002 (Non-cancer illness self-reported): value_type=22
        # categorical_multiple. RAP stores as embedded array → no _a suffix.
        names = ukb_codebook.field_to_rap_names(20002, instance=0)
        for n in names:
            assert "_a" not in n, (
                f"categorical_multiple {n} must NOT expand _a — RAP "
                f"returns this as an array-typed single column"
            )
        assert names == ["p20002_i0"]

    def test_all_instances_expansion(self, ukb_codebook):
        # BMI across all 4 instances
        names = ukb_codebook.field_to_rap_names(21001, all_instances=True)
        assert "p21001_i0" in names
        assert "p21001_i1" in names
        assert "p21001_i2" in names
        assert "p21001_i3" in names

    def test_unknown_field_returns_bare_name(self, ukb_codebook):
        # Unknown field_ids still emit something usable (no crash).
        names = ukb_codebook.field_to_rap_names(9999999)
        assert names == ["p9999999"]


class TestGenerateFieldList:
    """Test the disease-aware RAP .txt generator — the user's primary RAG entry point."""

    def test_baseline_only_falls_through_kb(self, ukb_codebook, tmp_path):
        out = tmp_path / "baseline.txt"
        fields = ukb_codebook.generate_field_list("baseline", output_path=out)
        assert "eid" in fields
        # Baseline covariates we expect in the template
        assert "p21001_i0" in fields  # BMI
        assert "p31" in fields         # Sex
        assert "p4080_i0_a0" in fields  # Systolic BP

        import json as _json
        prov = _json.loads(out.with_suffix(".txt.provenance.json").read_text())
        assert prov["disease_kb"]["matched"] is False
        assert "disease_kb" not in prov["section_columns"]
        assert prov["disease_requested"] == "baseline"

    def test_type_2_diabetes_adds_definition_fields(self, ukb_codebook, tmp_path):
        out = tmp_path / "t2d.txt"
        fields = ukb_codebook.generate_field_list("type_2_diabetes", output_path=out)

        # Fields from disease KB's ukb_definition_fields for T2D
        assert "p30750_i0" in fields  # HbA1c
        assert "p30740_i0" in fields  # Glucose
        assert "p2443_i0" in fields   # Doctor-diagnosed diabetes
        # First-occurrence T2D (E11) — specifically added by KB, NOT in template
        assert "p130708" in fields

        import json as _json
        prov = _json.loads(out.with_suffix(".txt.provenance.json").read_text())
        assert prov["disease_kb"]["matched"] is True
        assert prov["disease_kb"]["key"] == "type_2_diabetes"
        assert 130708 in prov["disease_kb"]["fields"]
        # disease_kb section in ownership should claim the truly new field
        assert "p130708" in prov["section_columns"].get("disease_kb", [])

    def test_hypertension_differs_from_t2d(self, ukb_codebook, tmp_path):
        t2d_out = tmp_path / "t2d.txt"
        htn_out = tmp_path / "htn.txt"
        t2d_fields = set(ukb_codebook.generate_field_list("type_2_diabetes",
                                                         output_path=t2d_out))
        htn_fields = set(ukb_codebook.generate_field_list("hypertension",
                                                         output_path=htn_out))
        # I10 first-occurrence field (131286) is HTN-specific; 130708 is T2D-specific
        assert "p131286" in htn_fields
        assert "p131286" not in t2d_fields
        assert "p130708" in t2d_fields
        assert "p130708" not in htn_fields

    def test_unknown_disease_key_does_not_crash(self, ukb_codebook, tmp_path):
        out = tmp_path / "unknown.txt"
        fields = ukb_codebook.generate_field_list("never_heard_of_it",
                                                  output_path=out)
        assert "eid" in fields  # template still runs
        import json as _json
        prov = _json.loads(out.with_suffix(".txt.provenance.json").read_text())
        assert prov["disease_kb"]["matched"] is False

    def test_missing_disease_kb_path_does_not_crash(self, ukb_codebook, tmp_path):
        out = tmp_path / "nokb.txt"
        fields = ukb_codebook.generate_field_list(
            "type_2_diabetes",
            output_path=out,
            disease_kb_path=tmp_path / "nonexistent.json",
        )
        assert "eid" in fields
        import json as _json
        prov = _json.loads(out.with_suffix(".txt.provenance.json").read_text())
        assert prov["disease_kb"]["matched"] is False
        assert "error" in prov["disease_kb"]

    def test_no_provenance_flag_suppresses_sidecar(self, ukb_codebook, tmp_path):
        out = tmp_path / "noprov.txt"
        ukb_codebook.generate_field_list("type_2_diabetes",
                                         output_path=out, write_provenance=False)
        assert out.exists()
        assert not (tmp_path / "noprov.txt.provenance.json").exists()

    def test_output_is_pristine_for_rap(self, ukb_codebook, tmp_path):
        # RAP Table Exporter expects ONE column name per line and nothing else.
        # No comment lines, no blank lines, no BOM.
        out = tmp_path / "rap.txt"
        ukb_codebook.generate_field_list("type_2_diabetes", output_path=out)
        text = out.read_text(encoding="utf-8")
        assert not text.startswith("﻿"), "No BOM"
        for i, line in enumerate(text.splitlines()):
            assert line.strip(), f"line {i} is blank"
            assert not line.startswith("#"), f"line {i} is a comment: {line!r}"

    def test_deduplication_keeps_first_section_ownership(self, ukb_codebook, tmp_path):
        # Field 30750 (HbA1c) is in BOTH laboratory_common AND T2D KB.
        # Deduplication must keep the column ONCE and attribute it to
        # whichever section emitted first (laboratory_common).
        out = tmp_path / "dedup.txt"
        fields = ukb_codebook.generate_field_list("type_2_diabetes",
                                                  output_path=out)
        assert fields.count("p30750_i0") == 1

        import json as _json
        prov = _json.loads(out.with_suffix(".txt.provenance.json").read_text())
        assert "p30750_i0" in prov["section_columns"]["laboratory_common"]
        assert "p30750_i0" not in prov["section_columns"].get("disease_kb", [])


class TestExcludeRisk:
    """--exclude-risk drops field_ids whose risk_category is blocklisted."""

    def test_field_ids_by_risk_returns_expected_shape(self, ukb_codebook):
        # Must return only field_ids matching the risk set — no NULLs, no junk.
        fids = ukb_codebook.field_ids_by_risk(["death_registry"])
        assert fids, "death_registry must yield >=1 field"
        assert all(isinstance(f, int) for f in fids)
        # Sanity: 40000 (Date of death) is the canonical death_registry field
        assert 40000 in fids

    def test_empty_risk_list_returns_empty(self, ukb_codebook):
        assert ukb_codebook.field_ids_by_risk([]) == []

    def test_exclude_outcome_derived_drops_first_occurrence(self, ukb_codebook, tmp_path):
        # T2D definition fields include 130708 (E11 first occurrence,
        # risk=outcome_derived). With --exclude-risk outcome_derived, it
        # must disappear from the extraction.
        out = tmp_path / "clean.txt"
        fields = ukb_codebook.generate_field_list(
            "type_2_diabetes",
            output_path=out,
            exclude_risk=["outcome_derived"],
        )
        assert "p130708" not in fields, "E11 first-occurrence must be excluded"
        # Baseline labs / anthropometry / BP still there
        assert "p21001_i0" in fields   # BMI
        assert "p30750_i0" in fields   # HbA1c (risk=baseline)
        assert "p4080_i0_a0" in fields  # Systolic BP

    def test_exclude_cascade_death_hospital_outcome(self, ukb_codebook, tmp_path):
        # Typical "clean feature extraction" invocation: drop all three
        # post-baseline outcome families at once.
        out = tmp_path / "feat.txt"
        fields = ukb_codebook.generate_field_list(
            "type_2_diabetes",
            output_path=out,
            exclude_risk=["outcome_derived", "death_registry", "hospital_derived"],
        )
        for excluded in ["p40000_i0", "p40001_i0", "p41270", "p41272",
                         "p41280", "p41282", "p130708", "p130709"]:
            assert excluded not in fields, f"{excluded} must be excluded"

    def test_exclude_is_recorded_in_provenance(self, ukb_codebook, tmp_path):
        out = tmp_path / "prov.txt"
        ukb_codebook.generate_field_list(
            "type_2_diabetes",
            output_path=out,
            exclude_risk=["outcome_derived", "death_registry"],
        )
        import json as _json
        prov = _json.loads(out.with_suffix(".txt.provenance.json").read_text())
        assert prov["exclude_risk"] == ["death_registry", "outcome_derived"]
        assert 40000 in prov["excluded_field_ids"]
        assert 130708 in prov["excluded_field_ids"]

    def test_exclude_unknown_risk_label_noops(self, ukb_codebook, tmp_path):
        # Passing a risk_category that doesn't exist should silently do nothing,
        # not crash. Protects against typos like "outcome_derivd".
        out_a = tmp_path / "baseline.txt"
        out_b = tmp_path / "typo.txt"
        baseline = ukb_codebook.generate_field_list(
            "type_2_diabetes", output_path=out_a,
        )
        with_typo = ukb_codebook.generate_field_list(
            "type_2_diabetes", output_path=out_b,
            exclude_risk=["outcome_derivd"],  # typo
        )
        assert baseline == with_typo

    def test_exclude_risk_does_not_affect_eid(self, ukb_codebook, tmp_path):
        # Even with aggressive exclusion the `eid` column must stay — it's
        # the primary key, RAP extraction is useless without it.
        out = tmp_path / "eid.txt"
        fields = ukb_codebook.generate_field_list(
            "type_2_diabetes",
            output_path=out,
            exclude_risk=["outcome_derived", "death_registry", "hospital_derived",
                          "online_followup", "imaging", "genomics"],
        )
        assert fields[0] == "eid"
