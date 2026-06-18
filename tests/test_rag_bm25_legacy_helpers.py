"""W8-W8: smoke tests for ``scripts.rag.retrieval.bm25`` legacy public helpers.

Wave 7 audit P8 flagged six public retrieval/formatter functions as
uncovered (48% module coverage). The hot path is ``retrieve_for_failure``;
these legacy helpers are still part of the public API surface used by
downstream tools and notebooks, so silent breakage matters. This module
adds parametric smoke + invariant tests that pin signatures, return
types, and the small set of behavioral guarantees each helper makes
(empty input → empty result, severity filter respected, display caps
honored by ``format_peer_context``).

Source is read-only: if a helper's signature drifts, fix the test, not
the source.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.rag.retrieval import bm25

KB_PATH = Path("references/case-studies/peer-review-kb.json")


@pytest.fixture(scope="module")
def kb_data():
    """Load the on-disk KB once per module to derive realistic test inputs."""
    with KB_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def sample_category(kb_data):
    for entry in kb_data["entries"]:
        for c in entry.get("reviewer_concerns", []):
            cat = c.get("category")
            if cat:
                return cat
    pytest.skip("KB has no concern with a category")


@pytest.fixture(scope="module")
def sample_domain(kb_data):
    for entry in kb_data["entries"]:
        if entry.get("domain"):
            return entry["domain"]
    pytest.skip("KB has no entry with a domain")


@pytest.fixture(scope="module")
def sample_paper(kb_data):
    """Return (paper_id, paper_doi) from the first entry that has both."""
    for entry in kb_data["entries"]:
        pid = entry.get("id")
        doi = entry.get("paper_doi", "")
        if pid:
            return pid, doi
    pytest.skip("KB has no entry with an id")


# ─── retrieve_by_text ────────────────────────────────────────────────


class TestRetrieveByText:
    def test_returns_enriched_concerns(self):
        results = bm25.retrieve_by_text("calibration", limit=3)
        assert isinstance(results, list)
        assert len(results) <= 3
        for r in results:
            assert "concern_id" in r
            assert "_paper_id" in r  # _enrich_concern fields present
            assert "_match_score" in r
            assert "_match_ratio" in r

    def test_empty_query_returns_empty(self):
        assert bm25.retrieve_by_text("", limit=3) == []

    def test_only_stopwords_returns_empty(self):
        # "the and for" tokens are all in _STOPWORDS or len<=2 after filtering
        assert bm25.retrieve_by_text("the and for", limit=3) == []

    def test_results_ranked_by_match_ratio_desc(self):
        results = bm25.retrieve_by_text("calibration overfitting validation", limit=10)
        if len(results) >= 2:
            ratios = [r["_match_ratio"] for r in results]
            assert ratios == sorted(ratios, reverse=True)

    def test_severity_filter_respected(self):
        results = bm25.retrieve_by_text("calibration", severity="CRITICAL", limit=10)
        for r in results:
            assert r.get("severity") == "CRITICAL"

    def test_limit_respected(self):
        results = bm25.retrieve_by_text("calibration", limit=2)
        assert len(results) <= 2


# ─── retrieve_for_failure ────────────────────────────────────────────


class TestRetrieveForFailure:
    def test_excluded_paper_ids_drop_holdout_before_limit(self, tmp_path):
        kb_path = tmp_path / "peer-review-kb.json"
        kb_path.write_text(json.dumps({
            "entries": [
                {
                    "id": "PR-SELF",
                    "paper_doi": "10.1/self",
                    "paper_title": "Holdout case",
                    "year": 2026,
                    "domain": "test",
                    "reviewer_concerns": [
                        {
                            "concern_id": "PR-SELF-C01",
                            "severity": "CRITICAL",
                            "mlgg_gates": ["leakage_gate"],
                            "tags": ["target_leakage"],
                            "concern_text": "Target leakage via an outcome proxy.",
                            "author_response": "Removed the leaking feature.",
                        }
                    ],
                },
                {
                    "id": "PR-OTHER",
                    "paper_doi": "10.1/other",
                    "paper_title": "Neighbor case",
                    "year": 2026,
                    "domain": "test",
                    "reviewer_concerns": [
                        {
                            "concern_id": "PR-OTHER-C01",
                            "severity": "HIGH",
                            "mlgg_gates": ["leakage_gate"],
                            "tags": ["target_leakage"],
                            "concern_text": "Target leakage via an outcome proxy.",
                            "author_response": "Removed the leaking feature.",
                        }
                    ],
                },
            ]
        }), encoding="utf-8")

        results = bm25.retrieve_for_failure(
            "leakage_gate",
            ["target_leakage"],
            limit=1,
            kb_path=kb_path,
            excluded_paper_ids=["PR-SELF", "10.1/self"],
        )

        assert [r["_paper_id"] for r in results] == ["PR-OTHER"]


# ─── retrieve_by_category ────────────────────────────────────────────


class TestRetrieveByCategory:
    def test_known_category_returns_list(self, sample_category):
        results = bm25.retrieve_by_category(sample_category, limit=3)
        assert isinstance(results, list)
        for r in results:
            assert r.get("category") == sample_category

    def test_unknown_category_returns_empty(self):
        assert bm25.retrieve_by_category("zzz_nonexistent_category", limit=3) == []

    def test_limit_respected(self, sample_category):
        results = bm25.retrieve_by_category(sample_category, limit=1)
        assert len(results) <= 1

    def test_severity_filter_respected(self, sample_category):
        results = bm25.retrieve_by_category(sample_category, severity="CRITICAL", limit=10)
        for r in results:
            assert r.get("severity") == "CRITICAL"


# ─── retrieve_by_domain ──────────────────────────────────────────────


class TestRetrieveByDomain:
    def test_known_domain_returns_list(self, sample_domain):
        results = bm25.retrieve_by_domain(sample_domain, limit=3)
        assert isinstance(results, list)
        for r in results:
            assert r.get("_domain") == sample_domain

    def test_unknown_domain_returns_empty(self):
        assert bm25.retrieve_by_domain("zzz_nonexistent_domain", limit=3) == []

    def test_limit_respected(self, sample_domain):
        results = bm25.retrieve_by_domain(sample_domain, limit=2)
        assert len(results) <= 2


# ─── retrieve_by_paper ───────────────────────────────────────────────


class TestRetrieveByPaper:
    def test_known_paper_id_returns_list(self, sample_paper):
        pid, _ = sample_paper
        results = bm25.retrieve_by_paper(pid, limit=50)
        assert isinstance(results, list)
        assert len(results) >= 1
        for r in results:
            assert r.get("_paper_id") == pid

    def test_case_insensitive(self, sample_paper):
        pid, _ = sample_paper
        lower = bm25.retrieve_by_paper(pid.lower(), limit=50)
        upper = bm25.retrieve_by_paper(pid.upper(), limit=50)
        assert len(lower) == len(upper)

    def test_doi_fragment_match(self, sample_paper):
        _, doi = sample_paper
        if not doi:
            pytest.skip("sample paper has no DOI")
        # Use a unique tail of the DOI as a fragment
        fragment = doi.split("/")[-1]
        results = bm25.retrieve_by_paper(fragment, limit=50)
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_unknown_paper_returns_empty(self):
        assert bm25.retrieve_by_paper("PR-zzz-nonexistent", limit=10) == []


# ─── retrieve_combined ───────────────────────────────────────────────


class TestRetrieveCombined:
    def test_no_filters_returns_results(self):
        # With no filters, every concern matches; capped by limit
        results = bm25.retrieve_combined(limit=5)
        assert isinstance(results, list)
        assert len(results) <= 5

    def test_category_only_matches_retrieve_by_category(self, sample_category):
        combined = bm25.retrieve_combined(category=sample_category, limit=5)
        by_cat = bm25.retrieve_by_category(sample_category, limit=5)
        # Same underlying _collect_concerns ordering → same concern_id set
        assert {c["concern_id"] for c in combined} == {c["concern_id"] for c in by_cat}

    def test_and_logic_narrows_results(self, sample_category, sample_domain):
        cat_only = bm25.retrieve_combined(category=sample_category, limit=100)
        combined = bm25.retrieve_combined(
            category=sample_category, domain=sample_domain, limit=100
        )
        # AND-ing in another filter cannot grow the result set
        assert len(combined) <= len(cat_only)

    def test_unknown_combo_returns_empty(self):
        results = bm25.retrieve_combined(
            category="zzz_nonexistent", domain="zzz_nonexistent", limit=5
        )
        assert results == []

    def test_severity_filter_respected(self, sample_category):
        results = bm25.retrieve_combined(
            category=sample_category, severity="CRITICAL", limit=10
        )
        for r in results:
            assert r.get("severity") == "CRITICAL"


# ─── format_peer_context ─────────────────────────────────────────────


class TestFormatPeerContext:
    def test_empty_list_returns_no_match_string(self):
        out = bm25.format_peer_context([])
        assert isinstance(out, str)
        assert "No matching peer review examples found" in out

    def test_single_concern_includes_id(self):
        concerns = [{
            "concern_id": "PR-XXX-C01",
            "_paper_id": "PR-XXX",
            "_year": 2024,
            "severity": "HIGH",
            "concern_text": "Example concern about calibration.",
            "author_response": "Authors added recalibration.",
            "tags": ["calibration", "validation"],
        }]
        out = bm25.format_peer_context(concerns)
        assert "PR-XXX-C01" in out
        assert "HIGH" in out
        assert "calibration" in out.lower()

    def test_max_display_caps_lines(self):
        # 5 concerns, max_display=2 → only first 2 rendered + a "more" footer
        concerns = [
            {
                "concern_id": f"PR-X-C0{i}",
                "_paper_id": "PR-X",
                "_year": 2024,
                "severity": "HIGH",
                "concern_text": f"Concern {i}",
                "author_response": "Fix",
                "tags": ["x"],
            }
            for i in range(5)
        ]
        out = bm25.format_peer_context(concerns, max_display=2)
        assert "PR-X-C00" in out
        assert "PR-X-C01" in out
        assert "PR-X-C02" not in out
        assert "and 3 more" in out

    def test_critical_gets_longer_text(self):
        long_text = "x" * 500
        critical = [{
            "concern_id": "C1", "_paper_id": "P", "_year": 2024,
            "severity": "CRITICAL", "concern_text": long_text,
            "author_response": "fix", "tags": ["t"],
        }]
        non_critical = [{
            "concern_id": "C1", "_paper_id": "P", "_year": 2024,
            "severity": "LOW", "concern_text": long_text,
            "author_response": "fix", "tags": ["t"],
        }]
        crit_out = bm25.format_peer_context(critical, max_text_len=150)
        low_out = bm25.format_peer_context(non_critical, max_text_len=150)
        # CRITICAL gets 250 chars vs 150 for LOW
        assert len(crit_out) > len(low_out)

    def test_generic_fix_suppressed(self):
        concerns = [{
            "concern_id": "C1", "_paper_id": "P", "_year": 2024,
            "severity": "HIGH", "concern_text": "real concern",
            "author_response": "Addressed in revision.",  # in _GENERIC_FIXES
            "tags": ["t"],
        }]
        out = bm25.format_peer_context(concerns)
        assert "Fix:" not in out

    def test_real_concerns_from_retrieval_render(self):
        # End-to-end smoke: retrieval output flows through formatter cleanly
        concerns = bm25.retrieve_by_text("calibration", limit=2)
        out = bm25.format_peer_context(concerns)
        assert isinstance(out, str)
        assert len(out) > 0
