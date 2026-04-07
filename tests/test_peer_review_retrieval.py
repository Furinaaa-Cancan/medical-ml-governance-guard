"""Tests for peer review knowledge base retrieval."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _peer_review_retrieval import (
    TAG_SYNONYMS,
    _expand_tags,
    _sort_by_severity,
    count_concerns_with_tag,
    format_gate_peer_context,
    format_peer_context,
    get_stats_summary,
    retrieve_by_category,
    retrieve_by_dimension,
    retrieve_by_domain,
    retrieve_by_gate,
    retrieve_by_tags,
    retrieve_by_text,
)

KB_PATH = Path(__file__).resolve().parents[1] / "references" / "peer_reviews" / "peer-review-kb.json"
STATS_PATH = Path(__file__).resolve().parents[1] / "references" / "peer_reviews" / "peer-review-kb-stats.json"


class TestSortBySeverity:
    def test_severity_order(self):
        concerns = [
            {"severity": "LOW"},
            {"severity": "CRITICAL"},
            {"severity": "MEDIUM"},
            {"severity": "HIGH"},
        ]
        result = _sort_by_severity(concerns)
        assert [c["severity"] for c in result] == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class TestRetrieveByDimension:
    def test_dimension_5_returns_results(self):
        results = retrieve_by_dimension(5, limit=3, kb_path=KB_PATH)
        assert len(results) > 0
        assert all(r.get("mlgg_dimension") == 5 for r in results)

    def test_dimension_with_severity_filter(self):
        results = retrieve_by_dimension(1, severity="CRITICAL", limit=10, kb_path=KB_PATH)
        assert all(r.get("severity") == "CRITICAL" for r in results)

    def test_enriched_fields_present(self):
        results = retrieve_by_dimension(5, limit=1, kb_path=KB_PATH)
        if results:
            assert "_paper_id" in results[0]
            assert "_paper_doi" in results[0]
            assert "_year" in results[0]


class TestRetrieveByGate:
    def test_leakage_gate(self):
        results = retrieve_by_gate("leakage_gate", kb_path=KB_PATH)
        assert len(results) > 0
        assert all("leakage_gate" in r.get("mlgg_gates", []) for r in results)

    def test_nonexistent_gate_returns_empty(self):
        results = retrieve_by_gate("nonexistent_gate_xyz", kb_path=KB_PATH)
        assert results == []


class TestRetrieveByTags:
    def test_single_tag(self):
        results = retrieve_by_tags(["missing_calibration"], kb_path=KB_PATH)
        assert len(results) > 0
        assert all("missing_calibration" in r.get("tags", []) for r in results)

    def test_multiple_tags_any(self):
        results = retrieve_by_tags(
            ["missing_calibration", "no_external_validation"],
            match_any=True,
            kb_path=KB_PATH,
        )
        for r in results:
            tags = set(r.get("tags", []))
            assert "missing_calibration" in tags or "no_external_validation" in tags


class TestRetrieveByCategory:
    def test_evaluation_metrics(self):
        results = retrieve_by_category("evaluation_metrics", limit=5, kb_path=KB_PATH)
        assert len(results) > 0
        assert all(r.get("category") == "evaluation_metrics" for r in results)


class TestRetrieveByDomain:
    def test_oncology(self):
        results = retrieve_by_domain("oncology", limit=5, kb_path=KB_PATH)
        assert len(results) > 0
        assert all(r.get("_domain") == "oncology" for r in results)


class TestGetStatsSummary:
    def test_stats_loads(self):
        stats = get_stats_summary(kb_path=STATS_PATH)
        assert stats["total_papers"] == 106
        assert stats["total_concerns"] == 375
        assert "concerns_by_category" in stats
        assert "concerns_by_severity" in stats


class TestCountConcernsWithTag:
    def test_known_tag(self):
        count = count_concerns_with_tag("missing_calibration", kb_path=KB_PATH)
        assert count >= 3  # We know at least 3 from our parsing


class TestFormatPeerContext:
    def test_format_nonempty(self):
        concerns = retrieve_by_dimension(5, limit=2, kb_path=KB_PATH)
        output = format_peer_context(concerns, max_display=2)
        assert "[" in output  # severity bracket
        assert "Concern:" in output

    def test_format_empty(self):
        output = format_peer_context([], max_display=3)
        assert "No matching" in output


class TestFormatGatePeerContext:
    def test_leakage_gate_context(self):
        output = format_gate_peer_context("leakage_gate", kb_path=KB_PATH)
        assert "Peer Review Context" in output

    def test_nonexistent_gate_empty(self):
        output = format_gate_peer_context("nonexistent_gate", kb_path=KB_PATH)
        assert output == ""


class TestSynonymExpansion:
    """Test that common problem descriptions find results via synonym mapping."""

    def test_fit_before_split_finds_leakage(self):
        results = retrieve_by_tags(["fit_before_split"], kb_path=KB_PATH)
        assert len(results) > 0

    def test_no_calibration_finds_calibration(self):
        results = retrieve_by_tags(["no_calibration"], kb_path=KB_PATH)
        assert len(results) > 0

    def test_overfitting_expands(self):
        results = retrieve_by_tags(["overfitting"], kb_path=KB_PATH)
        assert len(results) > 0

    def test_no_expand_flag(self):
        results = retrieve_by_tags(
            ["fit_before_split"], expand_synonyms=False, kb_path=KB_PATH
        )
        # Without expansion, this exact tag may not exist
        # Just verify it doesn't crash
        assert isinstance(results, list)

    def test_expand_tags_function(self):
        expanded = _expand_tags(["fit_before_split"])
        assert "future_information_leakage" in expanded
        assert "fit_before_split" in expanded  # original preserved


class TestRetrieveByText:
    """Test free-text search across concern text and tags."""

    def test_calibration_search(self):
        results = retrieve_by_text("calibration missing AUC only", kb_path=KB_PATH)
        assert len(results) > 0

    def test_leakage_search(self):
        results = retrieve_by_text("preprocessing before splitting data leakage", kb_path=KB_PATH)
        assert len(results) > 0

    def test_tripod_search(self):
        results = retrieve_by_text("TRIPOD reporting guidelines", kb_path=KB_PATH)
        assert len(results) > 0

    def test_empty_search_returns_empty(self):
        results = retrieve_by_text("", kb_path=KB_PATH)
        assert results == []

    def test_gibberish_returns_empty(self):
        results = retrieve_by_text("xyzqweasd", kb_path=KB_PATH)
        assert results == []

    def test_severity_filter_works(self):
        all_results = retrieve_by_text("sample size small", kb_path=KB_PATH, limit=50)
        critical_only = retrieve_by_text("sample size small", severity="CRITICAL", kb_path=KB_PATH, limit=50)
        assert len(critical_only) <= len(all_results)
        assert all(r.get("severity") == "CRITICAL" for r in critical_only)

    def test_match_score_ranking(self):
        results = retrieve_by_text("calibration missing AUC", kb_path=KB_PATH, limit=5)
        if len(results) >= 2:
            assert results[0]["_match_score"] >= results[1]["_match_score"]


class TestAllMajorGates:
    """Ensure peer review context exists for all major gates."""

    @pytest.mark.parametrize("gate", [
        "leakage_gate", "split_protocol_gate", "cohort_definition_gate",
        "evaluation_quality_gate", "calibration_dca_gate",
        "model_selection_audit_gate", "shap_interpretability_gate",
        "reporting_bias_gate", "missingness_policy_gate",
    ])
    def test_gate_has_peer_context(self, gate):
        ctx = format_gate_peer_context(gate, kb_path=KB_PATH)
        assert ctx != "", f"Gate {gate} should have peer review context"
