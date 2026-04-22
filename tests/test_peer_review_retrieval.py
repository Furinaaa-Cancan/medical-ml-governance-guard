"""Tests for peer review knowledge base retrieval."""

import json
import sys
from pathlib import Path

import pytest


from _peer_review_retrieval import (
    TAG_SYNONYMS,
    _expand_tags,
    _sort_by_severity,
    clear_cache,
    count_concerns_with_tag,
    format_gate_peer_context,
    format_peer_context,
    get_stats_summary,
    retrieve_by_category,
    retrieve_combined,
    retrieve_by_dimension,
    retrieve_by_domain,
    retrieve_by_gate,
    retrieve_by_paper,
    retrieve_by_tags,
    retrieve_by_text,
)

KB_PATH = Path(__file__).resolve().parents[1] / "references" / "case-studies" / "peer-review-kb.json"
STATS_PATH = Path(__file__).resolve().parents[1] / "references" / "case-studies" / "peer-review-kb-stats.json"


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
        """Stats file must stay consistent with the live KB. Rather than
        pinning counts that rot on every KB extension, assert stats totals
        equal the KB's actual entry/concern counts.
        """
        import json as _json
        kb = _json.loads(KB_PATH.read_text())
        live_papers = len(kb["entries"])
        live_concerns = sum(len(e.get("reviewer_concerns", [])) for e in kb["entries"])

        stats = get_stats_summary(kb_path=STATS_PATH)
        assert stats["total_papers"] == live_papers, (
            f"stats/paper count drift: stats={stats['total_papers']} vs "
            f"kb={live_papers} — regenerate peer-review-kb-stats.json"
        )
        assert stats["total_concerns"] == live_concerns, (
            f"stats/concern count drift: stats={stats['total_concerns']} vs "
            f"kb={live_concerns} — regenerate peer-review-kb-stats.json"
        )
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


class TestNewSynonyms:
    """Test newly added synonym groups."""

    @pytest.mark.parametrize("term", [
        "no_shap", "no_dca", "no_bootstrap", "temporal_leak",
        "label_leakage", "no_reproducibility", "confounding", "overstatement",
    ])
    def test_synonym_finds_results(self, term):
        results = retrieve_by_tags([term], kb_path=KB_PATH)
        assert len(results) >= 1, f"'{term}' returned 0 results"


class TestFixPrioritization:
    """Verify detailed fixes rank above generic ones."""

    def test_detailed_before_generic(self):
        results = retrieve_by_tags(["missing_calibration"], limit=10, kb_path=KB_PATH)
        # First result should have a detailed fix
        if results:
            fix = results[0].get("author_response", "")
            assert fix not in ("Addressed in revision.", "Addressed in revision", ""), \
                f"Top result has generic fix: '{fix}'"

    def test_format_skips_generic_fix(self):
        # Create a mock concern with generic fix
        mock = [{"concern_id": "TEST-01", "severity": "HIGH",
                 "concern_text": "Test concern", "author_response": "Addressed in revision.",
                 "_paper_id": "TEST", "_year": 2024, "tags": ["test"]}]
        fmt = format_peer_context(mock, max_display=1)
        assert "Fix:" not in fmt  # generic fix should be hidden




class TestRetrieveByPaper:
    """Test paper-specific retrieval."""

    def test_by_paper_id(self):
        r = retrieve_by_paper("PR-001", kb_path=KB_PATH)
        assert len(r) >= 5
        assert all(c.get("_paper_id") == "PR-001" for c in r)

    def test_by_doi_fragment(self):
        r = retrieve_by_paper("s41467-024-46663-4", kb_path=KB_PATH)
        assert len(r) >= 5

    def test_nonexistent_paper(self):
        r = retrieve_by_paper("PR-999", kb_path=KB_PATH)
        assert r == []


class TestRetrieveCombined:
    """Test multi-filter combined queries."""

    def test_dimension_and_domain(self):
        r = retrieve_combined(dimension=5, domain="oncology", kb_path=KB_PATH)
        assert len(r) >= 1
        assert all(c.get("mlgg_dimension") == 5 for c in r)
        assert all(c.get("_domain") == "oncology" for c in r)

    def test_category_and_severity(self):
        r = retrieve_combined(category="evaluation_metrics", severity="CRITICAL", kb_path=KB_PATH)
        assert all(c.get("category") == "evaluation_metrics" for c in r)
        assert all(c.get("severity") == "CRITICAL" for c in r)

    def test_no_filters_returns_all(self):
        r = retrieve_combined(limit=5, kb_path=KB_PATH)
        assert len(r) == 5

    def test_conflicting_filters_returns_empty(self):
        r = retrieve_combined(dimension=5, domain="nonexistent_domain", kb_path=KB_PATH)
        assert r == []


class TestCountWithSynonym:
    """Test count_concerns_with_tag with synonym expansion."""

    def test_count_with_synonym(self):
        count = count_concerns_with_tag("fit_before_split", expand_synonyms=True, kb_path=KB_PATH)
        assert count >= 2

    def test_count_without_synonym(self):
        count = count_concerns_with_tag("fit_before_split", expand_synonyms=False, kb_path=KB_PATH)
        # This exact tag may not exist in KB
        assert isinstance(count, int)


class TestClearCache:
    def test_clear_and_reload(self):
        # Load once
        retrieve_by_dimension(5, limit=1, kb_path=KB_PATH)
        # Clear
        clear_cache()
        # Should reload without error
        r = retrieve_by_dimension(5, limit=1, kb_path=KB_PATH)
        assert len(r) >= 1


class TestEdgeCases:
    """Verify no crashes on unusual inputs."""

    def test_empty_tags(self):
        assert retrieve_by_tags([], kb_path=KB_PATH) == []

    def test_none_in_tags(self):
        r = retrieve_by_tags([None, "missing_calibration"], kb_path=KB_PATH)
        assert isinstance(r, list)

    def test_int_in_tags(self):
        r = retrieve_by_tags([123, "missing_calibration"], kb_path=KB_PATH)
        assert isinstance(r, list)

    def test_unicode_tags(self):
        r = retrieve_by_tags(["校准缺失"], kb_path=KB_PATH)
        assert isinstance(r, list)

    def test_very_long_text_query(self):
        r = retrieve_by_text("a " * 500, kb_path=KB_PATH)
        assert isinstance(r, list)

    def test_invalid_dimension(self):
        r = retrieve_by_dimension(99, kb_path=KB_PATH)
        assert r == []

    def test_limit_zero(self):
        r = retrieve_by_dimension(5, limit=0, kb_path=KB_PATH)
        assert r == []

    def test_format_critical_gets_more_text(self):
        """CRITICAL concerns should show more text (250 chars vs 150)."""
        mock = [{"concern_id": "T-01", "severity": "CRITICAL",
                 "concern_text": "x" * 200, "author_response": "",
                 "_paper_id": "T", "_year": 2024, "tags": ["t"]}]
        fmt = format_peer_context(mock, max_display=1)
        # Should contain more than 150 x's
        assert fmt.count("x") > 150


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
