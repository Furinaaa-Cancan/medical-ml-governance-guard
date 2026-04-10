"""Tests for scripts/tools/nhanes_codebook_lookup.py — NHANES Codebook RAG."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


CODEBOOK_DIR = Path(__file__).resolve().parent.parent / "references" / "nhanes_codebook"
REGISTRY_PATH = Path(__file__).resolve().parent.parent / "references" / "dataset-codebook-registry.json"


@pytest.fixture(scope="module")
def codebook():
    """Load NHANESCodebook once for all tests in this module."""
    if not (CODEBOOK_DIR / "nhanes_variables.tsv").exists():
        pytest.skip("Harvard NHANES codebook TSVs not downloaded")
    from nhanes_codebook_lookup import NHANESCodebook
    return NHANESCodebook(str(CODEBOOK_DIR), cycle="2017-2018")


@pytest.fixture(scope="module")
def manual_registry() -> dict:
    if not REGISTRY_PATH.exists():
        pytest.skip("Manual codebook registry not found")
    with REGISTRY_PATH.open() as f:
        reg = json.load(f)
    return reg["datasets"]["nhanes_2017_2020"]["variables"]


# ────────────────────────────────────────────────────────
# Lookup tests
# ────────────────────────────────────────────────────────

class TestLookup:
    def test_known_variable(self, codebook):
        info = codebook.lookup("DIQ172")
        assert info is not None
        assert info["variable"] == "DIQ172"
        assert "risk" in info["sas_label"].lower() or "diabetes" in info["sas_label"].lower()

    def test_skip_pattern_detected(self, codebook):
        info = codebook.lookup("DIQ172")
        assert info["has_skip_pattern"] is True
        assert "DIQ180" in info["skip_pattern"].values()

    def test_missing_rate(self, codebook):
        info = codebook.lookup("BPQ050A")
        assert info["missing_rate"] > 0.5  # 68% missing

    def test_unknown_variable(self, codebook):
        assert codebook.lookup("NONEXISTENT_VAR") is None

    def test_inferred_type_continuous(self, codebook):
        info = codebook.lookup("RIDAGEYR")
        assert info["inferred_type"] == "continuous"

    def test_inferred_type_binary(self, codebook):
        info = codebook.lookup("SMQ020")
        assert info["inferred_type"] == "binary"

    def test_inferred_type_categorical(self, codebook):
        info = codebook.lookup("RIDRETH3")
        assert info["inferred_type"] == "categorical"

    def test_variable_count(self, codebook):
        assert codebook.variable_count > 3000

    def test_top_coded_variable(self, codebook):
        info = codebook.lookup("RIDAGEYR")
        # Should have "80 years of age and over" in codebook entries
        descs = [e["description"] for e in info["codebook"]]
        assert any("80" in d and "over" in d for d in descs)


# ────────────────────────────────────────────────────────
# Validation tests
# ────────────────────────────────────────────────────────

class TestValidation:
    def test_raw_nhanes_codes_detected(self, codebook):
        """Raw NHANES variable codes in CSV columns should be auto-validated."""
        issues = codebook.validate_columns(
            ["SEQN", "DIQ172", "RIDRETH3", "y"], target_col="y"
        )
        codes = [i["code"] for i in issues]
        # DIQ172 has skip pattern + missing → gated
        assert "CODEBOOK_GATED_MISSINGNESS" in codes
        # RIDRETH3 is categorical
        assert "CODEBOOK_ENCODING_CHECK" in codes

    def test_clean_friendly_names_no_issues(self, codebook, manual_registry):
        """Friendly-named columns already in manual registry → skipped by RAG."""
        issues = codebook.validate_columns(
            ["patient_id", "age", "gender", "bmi", "y"],
            target_col="y",
            manual_registry=manual_registry,
        )
        # age/gender/bmi are in manual registry → RAG skips them
        assert len(issues) == 0

    def test_manual_registry_has_priority(self, codebook, manual_registry):
        """Variables in manual registry should NOT be re-checked by RAG."""
        # Even if we pass raw codes that ARE in manual registry
        issues = codebook.validate_columns(
            ["RIDAGEYR", "RIDRETH3", "DIQ172", "y"],
            target_col="y",
            manual_registry=manual_registry,
        )
        # Manual registry has RIDAGEYR, RIDRETH3, DIQ172 → all skipped
        assert len(issues) == 0

    def test_non_nhanes_columns_safe(self, codebook):
        """Columns that don't match any NHANES variable → no issues."""
        issues = codebook.validate_columns(
            ["my_custom_feature", "another_feature", "y"], target_col="y"
        )
        assert len(issues) == 0


# ────────────────────────────────────────────────────────
# RAG vs Manual Registry consistency
# ────────────────────────────────────────────────────────

class TestRAGConsistency:
    """Verify RAG auto-retrieval is consistent with manual registry annotations."""

    def test_diq172_label_matches(self, codebook, manual_registry):
        """RAG label for DIQ172 must match manual registry label."""
        rag_info = codebook.lookup("DIQ172")
        manual_label = manual_registry["DIQ172"]["label"]
        # Both should say "Feel could be at risk"
        assert "risk" in rag_info["sas_label"].lower()
        assert "risk" in manual_label.lower()
        # Neither should say "family history"
        assert "family" not in rag_info["sas_label"].lower()
        assert "family" not in manual_label.lower()

    def test_bpq050a_gated_consistent(self, codebook, manual_registry):
        """Both RAG and manual registry agree BPQ050A has gated missingness."""
        rag_info = codebook.lookup("BPQ050A")
        manual = manual_registry["BPQ050A"]
        # RAG: high missing rate
        assert rag_info["missing_rate"] > 0.5
        # Manual: MNAR_gated mechanism
        assert "MNAR" in manual.get("missingness_mechanism", "")

    def test_ridreth3_categorical_consistent(self, codebook, manual_registry):
        """Both RAG and manual registry agree RIDRETH3 is categorical."""
        rag_info = codebook.lookup("RIDRETH3")
        manual = manual_registry["RIDRETH3"]
        assert rag_info["inferred_type"] == "categorical"
        assert manual.get("type") == "nominal_categorical"

    def test_smq020_binary_consistent(self, codebook, manual_registry):
        """RAG infers SMQ020 as binary; manual says binary."""
        rag_info = codebook.lookup("SMQ020")
        manual = manual_registry["SMQ020"]
        assert rag_info["inferred_type"] == "binary"
        assert manual.get("type") == "binary"

    def test_all_manual_vars_found_in_rag(self, codebook, manual_registry):
        """Every variable in manual registry must be findable via RAG."""
        missing = []
        for var_code in manual_registry:
            if codebook.lookup(var_code) is None:
                missing.append(var_code)
        assert missing == [], f"Manual registry vars not found in RAG: {missing}"


# ────────────────────────────────────────────────────────
# P0: Disease-KB × Codebook RAG (task-aware)
# ────────────────────────────────────────────────────────

DISEASE_KB_PATH = Path(__file__).resolve().parent.parent / "references" / "disease-definition-knowledge-base.json"


class TestTaskAwareValidation:
    """Test disease-KB × codebook RAG integration."""

    @pytest.fixture()
    def disease_kb(self) -> Path:
        if not DISEASE_KB_PATH.exists():
            pytest.skip("Disease definition KB not found")
        return DISEASE_KB_PATH

    def test_hba1c_flagged_for_diabetes(self, codebook, disease_kb):
        """HbA1c as feature when predicting diabetes → definition variable."""
        issues = codebook.task_aware_validate(
            ["SEQN", "hba1c", "age", "bmi", "y"],
            target_col="y",
            target_disease="type_2_diabetes",
            disease_kb_path=str(disease_kb),
        )
        codes = [i["details"]["var_code"] for i in issues]
        assert "LBXGH" in codes

    def test_fasting_glucose_flagged(self, codebook, disease_kb):
        """Fasting glucose flagged for diabetes prediction."""
        issues = codebook.task_aware_validate(
            ["SEQN", "fasting_glucose", "age", "y"],
            target_col="y",
            target_disease="diabetes",
            disease_kb_path=str(disease_kb),
        )
        codes = [i["details"]["var_code"] for i in issues]
        assert "LBXGLU" in codes

    def test_doctor_told_diabetes_flagged(self, codebook, disease_kb):
        """Self-report diabetes diagnosis flagged."""
        issues = codebook.task_aware_validate(
            ["SEQN", "doctor_told_diabetes", "age", "y"],
            target_col="y",
            target_disease="type_2_diabetes",
            disease_kb_path=str(disease_kb),
        )
        matched_terms = [i["details"]["matched_term"] for i in issues]
        assert any("diabetes" in t.lower() for t in matched_terms)

    def test_safe_features_not_flagged(self, codebook, disease_kb):
        """BMI, age, smoking should NOT be flagged for diabetes."""
        issues = codebook.task_aware_validate(
            ["SEQN", "age", "bmi", "ever_smoked", "y"],
            target_col="y",
            target_disease="type_2_diabetes",
            disease_kb_path=str(disease_kb),
        )
        assert len(issues) == 0

    def test_wrong_disease_no_flags(self, codebook, disease_kb):
        """HbA1c should NOT be flagged if predicting stroke (not diabetes)."""
        issues = codebook.task_aware_validate(
            ["SEQN", "hba1c", "age", "y"],
            target_col="y",
            target_disease="stroke",
            disease_kb_path=str(disease_kb),
        )
        # HbA1c is not a definition variable for stroke
        flagged_codes = [i["details"]["var_code"] for i in issues]
        assert "LBXGH" not in flagged_codes

    def test_missing_kb_returns_empty(self, codebook):
        """Non-existent KB path → empty list, no crash."""
        issues = codebook.task_aware_validate(
            ["SEQN", "hba1c", "y"],
            target_col="y",
            target_disease="diabetes",
            disease_kb_path="/nonexistent/kb.json",
        )
        assert issues == []


# ────────────────────────────────────────────────────────
# P1: Skip-chain ordering
# ────────────────────────────────────────────────────────

class TestSkipChain:
    """Test skip-chain graph resolution with corrected item ordering."""

    def test_bpq050a_gated_by_bpq020(self, codebook):
        """BPQ050A must be detected as gated by BPQ020."""
        chain = codebook.resolve_gating_chain("BPQ050A")
        assert chain["is_gated"]
        upstream_vars = [g["upstream_variable"] for g in chain["gated_by"]]
        assert "BPQ020" in upstream_vars

    def test_did040_gated_by_diq010(self, codebook):
        """DID040 (age when diagnosed) gated by DIQ010 (doctor told diabetes)."""
        chain = codebook.resolve_gating_chain("DID040")
        assert chain["is_gated"]
        upstream_vars = [g["upstream_variable"] for g in chain["gated_by"]]
        assert "DIQ010" in upstream_vars

    def test_table_var_order_preserved(self, codebook):
        """DIQ_J table variables should follow questionnaire item order."""
        codebook._ensure_index()
        order = codebook._table_var_order.get("DIQ_J", [])
        assert len(order) > 5
        # DIQ010 should come before DIQ160 which comes before DIQ172
        assert order.index("DIQ010") < order.index("DIQ160")
        assert order.index("DIQ160") < order.index("DIQ172")

    def test_ungated_variable(self, codebook):
        """RIDAGEYR (demographics) should not be gated."""
        chain = codebook.resolve_gating_chain("RIDAGEYR")
        assert not chain["is_gated"]
