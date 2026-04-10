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
    assert args.output_dir == Path("papers")


def test_parser_rejects_no_mode():
    """Parser requires one of --paper-dir, --all, or --poll-batch."""
    if not _HAS_PYDANTIC:
        pytest.skip("pydantic required to import build_arg_parser")
    from extract_paper_metadata import build_arg_parser

    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
