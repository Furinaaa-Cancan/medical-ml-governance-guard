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

    @pytest.mark.parametrize("column,expected", [
        # RAP (DNAnexus) format: p<field>_i<inst>_a<arr>
        ("p21001_i0_a0", (21001, 0, 0)),
        ("p4080_i1", (4080, 1, 0)),
        ("p41270", (41270, 0, 0)),
        ("p20002_i2", (20002, 2, 0)),
        # Data Showcase format: <field>-<inst>.<arr>
        ("21001-0.0", (21001, 0, 0)),
        ("4080-1.0", (4080, 1, 0)),
        ("30750-2.0", (30750, 2, 0)),
        # Bare field ID (assume instance=0, array=0)
        ("21001", (21001, 0, 0)),
        ("131286", (131286, 0, 0)),
        # Whitespace is stripped
        ("  p21001  ", (21001, 0, 0)),
    ])
    def test_parse_valid(self, column, expected):
        from scripts.codebooks.ukb_codebook_lookup import parse_ukb_column
        assert parse_ukb_column(column) == expected

    @pytest.mark.parametrize("column", [
        "age",                   # bare word
        "blood_pressure",        # underscore but no digits
        "eid",                   # primary key column
        "p",                     # 'p' without field_id
        "p_i0",                  # underscore with missing field
        "",                      # empty string
    ])
    def test_parse_unrecognized(self, column):
        from scripts.codebooks.ukb_codebook_lookup import parse_ukb_column
        assert parse_ukb_column(column) is None


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

    # ── Search canonical-match promotion ────────────────────────────
    # FTS5 BM25 alone buried canonical fields behind peripheral ones:
    # 'hba1c' returned 30755 (missing reason) / 30751 (assay date) /
    # 30754 (correction reason) before 30750 (the actual HbA1c
    # measurement). Alias + exact-title promotion must surface the
    # canonical field first.

    @pytest.mark.parametrize("query,expected_fid,reason", [
        # Medical acronyms curated in the aliases table — all of these
        # MUST surface their canonical field, not a peripheral one.
        ("hba1c", 30750, "regressions here cost real researcher time"),
        ("bmi", 21001, "21001 is baseline BMI; 23104 is imaging-derived"),
        ("glucose", 30740, "non-fasting serum glucose"),
        ("creatinine", 30700, "serum creatinine — eGFR denominator"),
        ("ldl", 30780, "LDL direct measurement"),
        ("hdl", 30760, "HDL cholesterol"),
        ("crp", 30710, "C-reactive protein (inflammation)"),
        ("triglycerides", 30870, "serum triglycerides"),
        ("sbp", 4080, "systolic BP — the aliased primary"),
        ("dbp", 4079, "diastolic BP — the aliased primary"),
        # Exact-title tier (no alias entry for full phrase)
        ("waist circumference", 48, "tier-1 exact-title match"),
        # Full-form aliases (avoids ambiguity with medical acronyms)
        ("t2dm", 130708, "Type 2 diabetes first-occurrence alias"),
    ])
    def test_search_promotes_canonical_field(
        self, ukb_codebook, query, expected_fid, reason,
    ):
        results = ukb_codebook.search(query, limit=5)
        assert results, f"search({query!r}) returned nothing"
        assert results[0]["field_id"] == expected_fid, (
            f"query={query!r} ({reason}): expected field_id={expected_fid}, "
            f"got {results[0]['field_id']} {results[0]['title']!r}. "
            f"Alias/title promotion layer regressed."
        )

    def test_search_multi_word_no_alias_falls_back_to_bm25(self, ukb_codebook):
        # 'blood pressure' has no alias and no exact-title field. An
        # over-eager "title starts with query" promotion earlier caused
        # 'Blood pressure device ID' (36) to top the list. We want
        # BM25 to decide in this case — assert 36 is NOT first.
        results = ukb_codebook.search("blood pressure", limit=5)
        assert results, "must return >=1 result"
        assert results[0]["field_id"] != 36, (
            "Tier-2/3 over-promotion regressed: 'Blood pressure device "
            "ID' should not leapfrog BM25 ordering for an ambiguous "
            "multi-word query."
        )

    def test_search_alias_prepended_when_not_in_bm25_topN(self, ukb_codebook):
        # Even with limit=1, if the alias target isn't in BM25's
        # top-N, it must be inserted at the front. Covers the case
        # where a noisy peripheral field would crowd the alias out.
        results = ukb_codebook.search("hba1c", limit=1)
        assert len(results) == 1
        assert results[0]["field_id"] == 30750

    def test_search_fts_only_operators_returns_empty_not_error(self, ukb_codebook):
        # "AND OR NOT" is pure FTS5 operator tokens — after sanitization
        # nothing remains. Must return [] cleanly, not crash.
        assert ukb_codebook.search("AND OR NOT") == []
        assert ukb_codebook.search("  ") == []
        assert ukb_codebook.search("") == []


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

    def test_phi_identifier_flagged(self, ukb_codebook):
        """UKB private=1 PHI fields must trip the privacy/leakage flag.

        Field 33 = Date of birth (private=1). Year of birth (34) is
        deliberately coarsened by UKB and NOT private=1 — that's the
        public safe version. Field 20033 = Home location east coord
        (private=1, identifier_location).
        """
        issues = ukb_codebook.validate_columns_for_gate(
            column_names=["p33", "p20033", "p21001_i0_a0"],
            target_col="p2443_i0",
        )
        phi = [i for i in issues if i["code"] == "CODEBOOK_PHI_IDENTIFIER_AS_FEATURE"]
        flagged_fids = {i["details"]["field_id"] for i in phi}
        assert 33 in flagged_fids, "Date of birth must raise PHI leakage"
        assert 20033 in flagged_fids, "Home coordinate must raise PHI leakage"
        for i in phi:
            assert i["details"]["risk_category"] == "identifier_direct"

    def test_accelerometry_flagged_as_followup(self, ukb_codebook):
        """Accelerometry fields were previously baseline — now online_followup.

        Regression guard for 2026-04-23 round-6 fix (211 fields moved).
        """
        issues = ukb_codebook.validate_columns_for_gate(
            column_names=["p90012_i0", "p21001_i0_a0"],  # accelerometry + BMI
            target_col="p2443_i0",
        )
        fu = [i for i in issues if i["code"] == "CODEBOOK_DERIVED_OUTCOME_FIELD"
              and i["details"]["risk_category"] == "online_followup"]
        assert len(fu) >= 1, "Accelerometry must be flagged online_followup"


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

    # ── M5 offline guardrail for categorical_multiple ──────────────
    # UKB RAP Table Exporter stores `categorical_multiple` (value_type
    # =22) fields as array-typed single columns — so our generator
    # must emit `p{fid}_i{inst}` (NO `_a{arr}` suffix). If this rule
    # ever flips back to per-array expansion, RAP will return "column
    # not found" and the user's model ends up trained on empty data —
    # a silent failure. Pin a representative sample of the 171
    # categorical_multiple fields so the rule has offline coverage
    # even though end-to-end verification requires RAP access.

    @pytest.mark.parametrize("fid,description", [
        (20002, "Non-cancer illness self-reported (common predictor)"),
        (20003, "Medication treatment codes (common predictor)"),
        (20004, "Operation code self-reported"),
        (20001, "Cancer code self-reported"),
        (20107, "Illness of father (family history)"),
        (20110, "Illness of mother (family history)"),
        (20111, "Illness of siblings (family history)"),
        (6177, "Medication for BP/chol/diabetes (male)"),
        (6153, "Medication for BP/chol/diabetes (female)"),
        (6150, "Vascular/heart problems diagnosed"),
    ])
    def test_categorical_multiple_never_expands_array(
        self, ukb_codebook, fid, description,
    ):
        names = ukb_codebook.field_to_rap_names(fid, instance=0)
        # Verify the DB actually says this field is categorical_multiple —
        # otherwise the test silently skips the contract it claims to pin.
        import sqlite3 as _sql
        conn = _sql.connect(str(UKB_DB))
        row = conn.execute(
            "SELECT value_type, arrayed FROM fields WHERE field_id=?", (fid,),
        ).fetchone()
        conn.close()
        assert row, f"field {fid} not in DB — test fixture stale"
        assert row[0] == "categorical_multiple", (
            f"field {fid} ({description}): value_type={row[0]!r}, not "
            f"'categorical_multiple' — UKB may have reclassified; update test."
        )
        for n in names:
            assert "_a" not in n, (
                f"field {fid} ({description}): emitted {n!r}. "
                f"categorical_multiple fields MUST NOT carry _a suffix on "
                f"RAP — downstream extraction will silently return empty."
            )
        # And positive shape assertion — it should be exactly one column
        # per instance (or per all_instances expansion).
        assert len(names) == 1
        assert names[0] == f"p{fid}_i0"

    @pytest.mark.parametrize("fid,instance", [
        (21001, 0), (21001, 2),  # BMI
        (30750, 0),              # HbA1c
        (4080, 0),               # Systolic BP (arrayed)
        (20002, 1),              # categorical_multiple
        (31, 0),                 # Sex (not instanced)
        (41270, 0),              # Hospital ICD10 (not instanced)
    ])
    def test_parse_build_roundtrip(self, ukb_codebook, fid, instance):
        """Any column we emit must re-parse back to the same (fid, inst, arr).

        Guards against any future RAP format drift: if field_to_rap_names
        starts emitting a format parse_ukb_column doesn't recognize, the
        codebook contract is broken.
        """
        from scripts.codebooks.ukb_codebook_lookup import parse_ukb_column
        for col in ukb_codebook.field_to_rap_names(fid, instance=instance):
            parsed = parse_ukb_column(col)
            assert parsed is not None, f"emitted {col!r} failed to re-parse"
            p_fid, p_inst, _ = parsed
            assert p_fid == fid, f"{col!r}: parsed fid={p_fid}, expected {fid}"
            assert p_inst == instance, (
                f"{col!r}: parsed instance={p_inst}, expected {instance}"
            )


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
        # No comment lines, no blank lines, no BOM, no trailing whitespace,
        # no tabs. All columns must parse back to a valid UKB triple.
        from scripts.codebooks.ukb_codebook_lookup import parse_ukb_column
        out = tmp_path / "rap.txt"
        ukb_codebook.generate_field_list("type_2_diabetes", output_path=out)
        text = out.read_text(encoding="utf-8")
        assert not text.startswith("﻿"), "RAP .txt must not carry a BOM"
        lines = text.splitlines()
        assert lines, "output file is empty"
        assert lines[0] == "eid", "eid must be the very first line"
        seen: set = set()
        for i, line in enumerate(lines):
            assert line == line.strip(), (
                f"line {i} has leading/trailing whitespace: {line!r}"
            )
            assert line, f"line {i} is blank"
            assert not line.startswith("#"), f"line {i} is a comment: {line!r}"
            assert "\t" not in line, f"line {i} contains a tab: {line!r}"
            assert line not in seen, (
                f"line {i} duplicates an earlier column: {line!r}"
            )
            seen.add(line)
            if line != "eid":
                assert parse_ukb_column(line) is not None, (
                    f"line {i} {line!r} does not parse as a UKB column"
                )

    def test_output_is_deterministic(self, ukb_codebook, tmp_path):
        # Running twice with the same args must produce byte-identical
        # output. Catches nondeterministic ordering (set iteration, dict
        # iteration pre-3.7 artefacts, random seed leaks) that would make
        # audit trails disagree across reruns.
        out_a = tmp_path / "run_a.txt"
        out_b = tmp_path / "run_b.txt"
        a = ukb_codebook.generate_field_list(
            "type_2_diabetes", output_path=out_a, write_provenance=False,
        )
        b = ukb_codebook.generate_field_list(
            "type_2_diabetes", output_path=out_b, write_provenance=False,
        )
        assert a == b
        assert out_a.read_bytes() == out_b.read_bytes()

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
