"""Tests for peer review knowledge base retrieval."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _peer_review_retrieval import (
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
        assert stats["total_papers"] == 107
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
