"""Tests for scripts/tools/extract_paper_metadata.py — LLM-powered metadata extraction.

Mostly smoke tests since the tool depends on external APIs (DeepSeek / Claude).
Does NOT make actual API calls.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

TOOL_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "tools"
    / "extract_paper_metadata.py"
)


# ---------------------------------------------------------------------------
# CLI --help
# ---------------------------------------------------------------------------

def test_cli_help_exits_zero():
    """CLI --help should exit 0."""
    result = subprocess.run(
        [sys.executable, str(TOOL_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert "structured extraction" in result.stdout.lower() or "paper" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Pydantic models — guarded by try/except
# ---------------------------------------------------------------------------

try:
    from pydantic import ValidationError

    # Add tool's parent to path so we can import its models
    from extract_paper_metadata import (
        DatasetOut,
        ExtractionResult,
        LeakageRiskOut,
        ModelOut,
        PerformanceMetricsOut,
        ReportingStandardsOut,
        StudyDesignOut,
    )

    _HAS_PYDANTIC = True
except ImportError:
    _HAS_PYDANTIC = False


@pytest.mark.skipif(not _HAS_PYDANTIC, reason="pydantic not installed")
class TestPydanticModels:
    """Pydantic extraction schemas validate correctly."""

    def test_study_design_defaults(self):
        m = StudyDesignOut()
        assert m.prediction_type is None
        assert m.outcome is None

    def test_study_design_with_values(self):
        m = StudyDesignOut(
            prediction_type="binary_classification",
            outcome="30-day mortality",
            is_multicenter=True,
        )
        assert m.prediction_type == "binary_classification"
        assert m.is_multicenter is True

    def test_dataset_out_defaults(self):
        m = DatasetOut()
        assert m.n_patients_total is None
        assert m.split_strategy is None

    def test_dataset_out_with_values(self):
        m = DatasetOut(
            source_type="EHR_single_center",
            n_patients_total=5000,
            n_events_positive=350,
            prevalence_pct=7.0,
            split_strategy="temporal",
        )
        assert m.n_patients_total == 5000
        assert m.prevalence_pct == 7.0

    def test_model_out_defaults(self):
        m = ModelOut()
        assert m.model_type is None

    def test_performance_metrics_defaults(self):
        m = PerformanceMetricsOut()
        assert m.test_auroc is None
        assert m.dca_reported is None

    def test_reporting_standards_defaults(self):
        m = ReportingStandardsOut()
        assert m.tripod_ai_claimed is None

    def test_leakage_risk_defaults(self):
        m = LeakageRiskOut()
        assert m.patient_level_split_confirmed is None
        assert m.notes == ""

    def test_leakage_risk_with_notes(self):
        m = LeakageRiskOut(
            patient_level_split_confirmed=True,
            temporal_split_confirmed=False,
            target_leakage_risk="low",
            notes="Split strategy clearly described.",
        )
        assert m.patient_level_split_confirmed is True
        assert m.target_leakage_risk == "low"

    def test_extraction_result_full(self):
        """Full ExtractionResult should accept nested models."""
        result = ExtractionResult(
            study_design=StudyDesignOut(),
            dataset=DatasetOut(),
            model=ModelOut(),
            performance_metrics=PerformanceMetricsOut(),
            reporting_standards=ReportingStandardsOut(),
            leakage_risk=LeakageRiskOut(),
            extraction_confidence="high",
            extraction_notes="Abstract only.",
        )
        assert result.extraction_confidence == "high"

    def test_extraction_result_missing_required_field(self):
        """ExtractionResult without required fields should raise."""
        with pytest.raises(ValidationError):
            ExtractionResult(
                study_design=StudyDesignOut(),
                # missing other required nested models
            )

    def test_invalid_int_field_raises(self):
        """Passing a non-coercible type for int field should raise."""
        with pytest.raises(ValidationError):
            DatasetOut(n_patients_total="not_a_number")


# ---------------------------------------------------------------------------
# Path resolution for paper directories
# ---------------------------------------------------------------------------

def test_paper_dir_resolution(tmp_path):
    """A paper directory path resolves correctly."""
    paper_dir = tmp_path / "papers" / "nature_medicine" / "cardio" / "smith_2023"
    paper_dir.mkdir(parents=True)
    metadata_file = paper_dir / "metadata.json"
    metadata_file.write_text("{}")

    resolved = paper_dir.resolve()
    assert resolved.exists()
    assert (resolved / "metadata.json").exists()


def test_output_dir_default():
    """The default output-dir is 'papers' (relative)."""
    if not _HAS_PYDANTIC:
        pytest.skip("pydantic required to import build_arg_parser")
    from extract_paper_metadata import build_arg_parser

    parser = build_arg_parser()
    args = parser.parse_args(["--all"])
    assert args.output_dir == Path("references/case-studies")


def test_parser_rejects_no_mode():
    """Parser requires one of --paper-dir, --all, or --poll-batch."""
    if not _HAS_PYDANTIC:
        pytest.skip("pydantic required to import build_arg_parser")
    from extract_paper_metadata import build_arg_parser

    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


# ---------------------------------------------------------------------------
# Literal enum validation — rejects hallucinated values
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_PYDANTIC, reason="pydantic not installed")
class TestLiteralConstraints:
    """Literal-typed fields reject non-allowed values from LLM output."""

    def test_invalid_prediction_type_rejected(self):
        with pytest.raises(ValidationError):
            StudyDesignOut(prediction_type="classification")  # should be binary_classification

    def test_valid_prediction_type_accepted(self):
        m = StudyDesignOut(prediction_type="binary_classification")
        assert m.prediction_type == "binary_classification"

    def test_invalid_source_type_rejected(self):
        with pytest.raises(ValidationError):
            DatasetOut(source_type="electronic_health_records")  # should be EHR_single_center

    def test_invalid_split_strategy_rejected(self):
        with pytest.raises(ValidationError):
            DatasetOut(split_strategy="stratified_random")  # should be random

    def test_invalid_model_type_rejected(self):
        from extract_paper_metadata import ModelOut
        with pytest.raises(ValidationError):
            ModelOut(model_type="gradient_boosting")  # should be xgboost or lightgbm

    def test_invalid_tuning_set_rejected(self):
        from extract_paper_metadata import ModelOut
        with pytest.raises(ValidationError):
            ModelOut(tuning_set="test_set")  # should be test_used

    def test_invalid_risk_level_rejected(self):
        with pytest.raises(ValidationError):
            LeakageRiskOut(target_leakage_risk="moderate")  # should be medium

    def test_invalid_code_availability_rejected(self):
        with pytest.raises(ValidationError):
            ReportingStandardsOut(code_availability="github")  # should be public_github

    def test_invalid_data_availability_rejected(self):
        with pytest.raises(ValidationError):
            ReportingStandardsOut(data_availability="available")  # should be public

    def test_invalid_extraction_confidence_rejected(self):
        with pytest.raises(ValidationError):
            ExtractionResult(
                study_design=StudyDesignOut(),
                dataset=DatasetOut(),
                model=ModelOut(),
                performance_metrics=PerformanceMetricsOut(),
                reporting_standards=ReportingStandardsOut(),
                leakage_risk=LeakageRiskOut(),
                extraction_confidence="moderate",  # should be medium
                extraction_notes="test",
            )

    def test_null_enum_fields_accepted(self):
        """All Literal fields should accept None."""
        m = DatasetOut(source_type=None, split_strategy=None)
        assert m.source_type is None
        assert m.split_strategy is None


# ---------------------------------------------------------------------------
# Evidence quote fields
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_PYDANTIC, reason="pydantic not installed")
class TestEvidenceQuotes:
    """LeakageRiskOut evidence fields work correctly."""

    def test_evidence_fields_default_none(self):
        m = LeakageRiskOut()
        assert m.patient_level_split_evidence is None
        assert m.temporal_split_evidence is None
        assert m.preprocessing_evidence is None
        assert m.tuning_evidence is None

    def test_evidence_fields_with_quotes(self):
        m = LeakageRiskOut(
            patient_level_split_confirmed=True,
            patient_level_split_evidence="We ensured all records from the same patient were in the same fold.",
            temporal_split_confirmed=False,
            temporal_split_evidence="Random split was used for train-test partitioning.",
        )
        assert "same patient" in m.patient_level_split_evidence
        assert m.temporal_split_confirmed is False


# ---------------------------------------------------------------------------
# Numeric cross-validation (model_post_init)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_PYDANTIC, reason="pydantic not installed")
class TestNumericCrossValidation:
    """ExtractionResult model_post_init catches inconsistencies."""

    def _make_result(self, **overrides):
        """Helper to build ExtractionResult with overridable nested fields."""
        ds_kw = overrides.pop("dataset", {})
        pm_kw = overrides.pop("performance_metrics", {})
        return ExtractionResult(
            study_design=StudyDesignOut(),
            dataset=DatasetOut(**ds_kw),
            model=ModelOut(),
            performance_metrics=PerformanceMetricsOut(**pm_kw),
            reporting_standards=ReportingStandardsOut(),
            leakage_risk=LeakageRiskOut(),
            extraction_confidence="high",
            extraction_notes="test",
            **overrides,
        )

    def test_clean_data_no_warnings(self):
        r = self._make_result(
            dataset={"n_patients_total": 1000, "n_events_positive": 200, "n_events_negative": 800, "prevalence_pct": 20.0},
            performance_metrics={"test_auroc": 0.85, "test_auroc_ci_lower": 0.80, "test_auroc_ci_upper": 0.90},
        )
        assert r._validation_warnings == []

    def test_patient_count_mismatch(self):
        r = self._make_result(
            dataset={"n_patients_total": 1000, "n_events_positive": 200, "n_events_negative": 700},
        )
        assert any("n_events_positive" in w for w in r._validation_warnings)

    def test_prevalence_mismatch(self):
        r = self._make_result(
            dataset={"n_patients_total": 1000, "n_events_positive": 200, "prevalence_pct": 50.0},
        )
        assert any("prevalence_pct" in w for w in r._validation_warnings)

    def test_auroc_ci_inverted(self):
        r = self._make_result(
            performance_metrics={"test_auroc": 0.85, "test_auroc_ci_lower": 0.90, "test_auroc_ci_upper": 0.80},
        )
        warnings = r._validation_warnings
        assert any("ci_lower" in w.lower() or "CI inverted" in w for w in warnings)

    def test_auroc_out_of_range(self):
        r = self._make_result(
            performance_metrics={"test_auroc": 1.5},
        )
        assert any("outside [0, 1]" in w for w in r._validation_warnings)

    def test_metric_out_of_range(self):
        r = self._make_result(
            performance_metrics={"test_sensitivity": 95.0},  # likely percentage, not decimal
        )
        assert any("test_sensitivity" in w for w in r._validation_warnings)

    def test_split_sum_exceeds_total(self):
        r = self._make_result(
            dataset={"n_patients_total": 1000, "train_n": 700, "test_n": 500},
        )
        assert any("split sizes sum" in w for w in r._validation_warnings)

    def test_warnings_appended_to_notes(self):
        r = self._make_result(
            performance_metrics={"test_auroc": 1.5},
        )
        assert "VALIDATION:" in r.extraction_notes


# ---------------------------------------------------------------------------
# merge_extraction — LLM source tagging
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_PYDANTIC, reason="pydantic not installed")
class TestMergeExtraction:
    """merge_extraction correctly merges and tags LLM-extracted fields."""

    def _base_metadata(self):
        """Minimal metadata structure matching what fetch_papers.py creates."""
        return {
            "study_design": {},
            "dataset": {},
            "model": {},
            "performance_metrics": {},
            "reporting_standards": {},
            "leakage_risk_assessment": {},
        }

    def _make_result(self, **overrides):
        return ExtractionResult(
            study_design=StudyDesignOut(prediction_type="binary_classification"),
            dataset=DatasetOut(n_patients_total=5000, split_strategy="temporal"),
            model=ModelOut(model_type="xgboost"),
            performance_metrics=PerformanceMetricsOut(test_auroc=0.85),
            reporting_standards=ReportingStandardsOut(),
            leakage_risk=LeakageRiskOut(
                target_leakage_risk="low",
                patient_level_split_confirmed=True,
                patient_level_split_evidence="All records grouped by patient ID.",
                notes="Well-described methodology.",
            ),
            extraction_confidence="high",
            extraction_notes="Full text available.",
            **overrides,
        )

    def test_merge_fills_empty_fields(self):
        from extract_paper_metadata import merge_extraction
        metadata = self._base_metadata()
        result = self._make_result()
        merged = merge_extraction(metadata, result)

        assert merged["study_design"]["prediction_type"] == "binary_classification"
        assert merged["dataset"]["n_patients_total"] == 5000
        assert merged["model"]["model_type"] == "xgboost"
        assert merged["performance_metrics"]["test_auroc"] == 0.85

    def test_merge_does_not_overwrite_existing(self):
        from extract_paper_metadata import merge_extraction
        metadata = self._base_metadata()
        metadata["dataset"]["n_patients_total"] = 3000  # human-set value
        result = self._make_result()
        merged = merge_extraction(metadata, result, force=False)

        assert merged["dataset"]["n_patients_total"] == 3000  # preserved

    def test_merge_force_overwrites(self):
        from extract_paper_metadata import merge_extraction
        metadata = self._base_metadata()
        metadata["dataset"]["n_patients_total"] = 3000
        result = self._make_result()
        merged = merge_extraction(metadata, result, force=True)

        assert merged["dataset"]["n_patients_total"] == 5000  # overwritten

    def test_llm_source_tagging(self):
        from extract_paper_metadata import merge_extraction
        metadata = self._base_metadata()
        result = self._make_result()
        merged = merge_extraction(metadata, result)

        audit = merged["mlgg_audit"]
        assert audit["_source"] == "llm_extracted"
        assert "dataset.n_patients_total" in audit["_llm_extracted_fields"]
        assert "study_design.prediction_type" in audit["_llm_extracted_fields"]
        assert isinstance(audit["_validation_warnings"], list)

    def test_leakage_notes_appended(self):
        from extract_paper_metadata import merge_extraction
        metadata = self._base_metadata()
        metadata["leakage_risk_assessment"]["notes"] = "Existing note."
        result = self._make_result()
        merged = merge_extraction(metadata, result)

        notes = merged["leakage_risk_assessment"]["notes"]
        assert "Existing note." in notes
        assert "Well-described methodology." in notes

    def test_evidence_fields_merged(self):
        from extract_paper_metadata import merge_extraction
        metadata = self._base_metadata()
        result = self._make_result()
        merged = merge_extraction(metadata, result)

        leak = merged["leakage_risk_assessment"]
        assert leak["patient_level_split_evidence"] == "All records grouped by patient ID."


# ---------------------------------------------------------------------------
# assemble_paper_text
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_PYDANTIC, reason="pydantic not installed")
class TestAssemblePaperText:
    """assemble_paper_text builds prompt text correctly."""

    def test_empty_metadata_returns_empty(self):
        from extract_paper_metadata import assemble_paper_text
        result = assemble_paper_text({}, abstract_only=True)
        assert result == ""

    def test_title_and_abstract(self):
        from extract_paper_metadata import assemble_paper_text
        metadata = {
            "bibliographic": {"title": "Prediction of AF", "journal": "Nature Medicine", "year": "2023"},
            "auto_classification": {"abstract_snippet": "We developed a model..."},
        }
        text = assemble_paper_text(metadata, abstract_only=True)
        assert "Prediction of AF" in text
        assert "Nature Medicine" in text
        assert "We developed a model" in text

    def test_abstract_only_skips_fulltext(self):
        from extract_paper_metadata import assemble_paper_text
        metadata = {
            "bibliographic": {"title": "Test", "pmcid": "PMC1234567"},
            "auto_classification": {"abstract_snippet": "Abstract text."},
        }
        # abstract_only=True should not attempt PMC fetch
        text = assemble_paper_text(metadata, abstract_only=True)
        assert "FULL TEXT" not in text


# ---------------------------------------------------------------------------
# _extract_pmc_sections — XML parsing
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_PYDANTIC, reason="pydantic not installed")
class TestExtractPmcSections:
    """XML section extraction from PMC full-text."""

    def test_extracts_methods_section(self):
        from extract_paper_metadata import _extract_pmc_sections
        xml = b"""<article>
        <body>
            <sec><title>Introduction</title><p>Short intro.</p></sec>
            <sec><title>Methods</title><p>%s</p></sec>
            <sec><title>Results</title><p>%s</p></sec>
        </body>
        </article>""" % (b"X " * 100, b"Y " * 100)
        result = _extract_pmc_sections(xml)
        assert "Methods" in result or "X " in result
        assert "Results" in result or "Y " in result

    def test_invalid_xml_returns_empty(self):
        from extract_paper_metadata import _extract_pmc_sections
        assert _extract_pmc_sections(b"not xml at all") == ""

    def test_fallback_to_body_text(self):
        from extract_paper_metadata import _extract_pmc_sections
        xml = b"""<article><body><sec><title>Unusual Title</title><p>%s</p></sec></body></article>""" % (b"Z " * 200)
        result = _extract_pmc_sections(xml)
        assert len(result) > 0  # should fall back to body text


# ---------------------------------------------------------------------------
# Source-text verification (P1 — zero-cost hallucination checks)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_PYDANTIC, reason="pydantic not installed")
class TestVerifyNumericsInSource:
    """verify_numerics_in_source catches fabricated numbers."""

    def _make_result(self, **overrides):
        ds_kw = overrides.pop("dataset", {})
        pm_kw = overrides.pop("performance_metrics", {})
        return ExtractionResult(
            study_design=StudyDesignOut(),
            dataset=DatasetOut(**ds_kw),
            model=ModelOut(),
            performance_metrics=PerformanceMetricsOut(**pm_kw),
            reporting_standards=ReportingStandardsOut(),
            leakage_risk=LeakageRiskOut(),
            extraction_confidence="high",
            extraction_notes="test",
            **overrides,
        )

    def test_all_numbers_present(self):
        from extract_paper_metadata import verify_numerics_in_source
        result = self._make_result(
            dataset={"n_patients_total": 5000, "train_n": 3500, "test_n": 1500},
            performance_metrics={"test_auroc": 0.85, "test_sensitivity": 0.72},
        )
        text = "We enrolled 5000 patients. Training set: 3500, test set: 1500. AUROC 0.85, sensitivity 0.72."
        warnings = verify_numerics_in_source(result, text)
        assert warnings == []

    def test_missing_auroc_flagged(self):
        from extract_paper_metadata import verify_numerics_in_source
        result = self._make_result(
            performance_metrics={"test_auroc": 0.91},
        )
        text = "The model achieved an AUROC of 0.85 on the test set."
        warnings = verify_numerics_in_source(result, text)
        assert any("test_auroc" in w for w in warnings)

    def test_missing_sample_size_flagged(self):
        from extract_paper_metadata import verify_numerics_in_source
        result = self._make_result(
            dataset={"n_patients_total": 12345},
        )
        text = "We used data from 10000 patients."
        warnings = verify_numerics_in_source(result, text)
        assert any("n_patients_total" in w for w in warnings)

    def test_percentage_format_accepted(self):
        from extract_paper_metadata import verify_numerics_in_source
        result = self._make_result(
            performance_metrics={"test_auroc": 0.85},
        )
        text = "The model achieved 85% accuracy."
        warnings = verify_numerics_in_source(result, text)
        assert not any("test_auroc" in w for w in warnings)

    def test_comma_separated_number(self):
        from extract_paper_metadata import verify_numerics_in_source
        result = self._make_result(
            dataset={"n_patients_total": 101766},
        )
        text = "We included 101,766 patients in the study."
        warnings = verify_numerics_in_source(result, text)
        assert not any("n_patients_total" in w for w in warnings)

    def test_null_values_skipped(self):
        from extract_paper_metadata import verify_numerics_in_source
        result = self._make_result()  # all None
        warnings = verify_numerics_in_source(result, "Some paper text")
        assert warnings == []


@pytest.mark.skipif(not _HAS_PYDANTIC, reason="pydantic not installed")
class TestVerifyEvidenceQuotes:
    """verify_evidence_quotes catches fabricated evidence quotes."""

    def _make_result(self, **leak_kw):
        return ExtractionResult(
            study_design=StudyDesignOut(),
            dataset=DatasetOut(),
            model=ModelOut(),
            performance_metrics=PerformanceMetricsOut(),
            reporting_standards=ReportingStandardsOut(),
            leakage_risk=LeakageRiskOut(**leak_kw),
            extraction_confidence="high",
            extraction_notes="test",
        )

    def test_exact_quote_passes(self):
        from extract_paper_metadata import verify_evidence_quotes
        paper_text = "We ensured all records from the same patient were assigned to the same fold."
        result = self._make_result(
            patient_level_split_confirmed=True,
            patient_level_split_evidence="all records from the same patient were assigned to the same fold",
        )
        warnings = verify_evidence_quotes(result, paper_text)
        assert warnings == []

    def test_fabricated_quote_flagged(self):
        from extract_paper_metadata import verify_evidence_quotes
        paper_text = "We used a random 80/20 split for training and testing."
        result = self._make_result(
            patient_level_split_confirmed=True,
            patient_level_split_evidence="Patient-level clustering was applied using hierarchical grouping to prevent data leakage across folds",
        )
        warnings = verify_evidence_quotes(result, paper_text)
        assert any("EVIDENCE_MISMATCH" in w and "patient_level_split_evidence" in w for w in warnings)

    def test_partial_overlap_below_threshold(self):
        from extract_paper_metadata import verify_evidence_quotes
        paper_text = "Data was split randomly into training and test sets."
        result = self._make_result(
            temporal_split_confirmed=True,
            temporal_split_evidence="Data was split temporally using calendar year cutoffs to ensure prospective validation",
        )
        warnings = verify_evidence_quotes(result, paper_text, threshold=0.6)
        assert any("EVIDENCE_MISMATCH" in w for w in warnings)

    def test_none_evidence_skipped(self):
        from extract_paper_metadata import verify_evidence_quotes
        result = self._make_result()  # all evidence fields None
        warnings = verify_evidence_quotes(result, "Some paper text")
        assert warnings == []

    def test_short_evidence_skipped(self):
        from extract_paper_metadata import verify_evidence_quotes
        result = self._make_result(
            patient_level_split_evidence="yes",  # too short (<10 chars)
        )
        warnings = verify_evidence_quotes(result, "Some paper text")
        assert warnings == []
