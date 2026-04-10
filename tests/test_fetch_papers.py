"""Tests for the fetch_papers.py tool."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


TOOL_PATH = str(Path(__file__).resolve().parents[1] / "scripts" / "tools" / "fetch_papers.py")


# ---------------------------------------------------------------------------
# CLI tests (subprocess)
# ---------------------------------------------------------------------------
class TestCLIHelp:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, TOOL_PATH, "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0
        assert "Fetch medical ML papers" in result.stdout


class TestCLIDryRun:
    """--dry-run should not create any files on disk."""

    def test_dry_run_creates_no_files(self, tmp_path):
        """Run with --dry-run and mocked network; output dir stays empty."""
        # Mock _get to avoid network calls — return empty JSON for search
        with patch("fetch_papers._get", return_value=b'{"esearchresult": {"idlist": []}}'):
            import fetch_papers
            fetch_papers.main([
                "--query", "test query",
                "--sources", "pubmed",
                "--max-results", "5",
                "--output-dir", str(tmp_path / "papers"),
                "--dry-run",
                "--no-manifest-update",
            ])
        # Output dir should not exist (no results to write)
        papers_dir = tmp_path / "papers"
        if papers_dir.exists():
            files = list(papers_dir.rglob("*"))
            # Only dry-run log lines, no actual metadata.json
            assert not any(f.name == "metadata.json" for f in files)


# ---------------------------------------------------------------------------
# Unit tests: deduplicate()
# ---------------------------------------------------------------------------
class TestDeduplicate:
    def _paper(self, title="Test Paper", doi="", pmid="", abstract="", authors=None, mesh_terms=None, source="pubmed"):
        from fetch_papers import _empty_paper
        p = _empty_paper()
        p["title"] = title
        p["doi"] = doi
        p["pmid"] = pmid
        p["abstract"] = abstract
        p["authors"] = authors or []
        p["mesh_terms"] = mesh_terms or []
        p["source"] = source
        return p

    def test_no_duplicates_pass_through(self):
        from fetch_papers import deduplicate
        papers = [
            self._paper(title="Paper A", doi="10.1/a"),
            self._paper(title="Paper B", doi="10.1/b"),
        ]
        result = deduplicate(papers)
        assert len(result) == 2

    def test_duplicate_doi_kept_once(self):
        from fetch_papers import deduplicate
        papers = [
            self._paper(title="Paper A", doi="10.1/same"),
            self._paper(title="Paper A copy", doi="10.1/same"),
        ]
        result = deduplicate(papers)
        assert len(result) == 1

    def test_duplicate_title_kept_once(self):
        from fetch_papers import deduplicate
        papers = [
            self._paper(title="Identical Title Here"),
            self._paper(title="Identical Title Here"),
        ]
        result = deduplicate(papers)
        assert len(result) == 1

    def test_higher_score_record_wins(self):
        from fetch_papers import deduplicate
        sparse = self._paper(title="Paper X", doi="10.1/x", abstract="")
        rich = self._paper(title="Paper X dup", doi="10.1/x", abstract="Has abstract", authors=["A B", "C D", "E F"], pmid="12345")
        result = deduplicate([sparse, rich])
        assert len(result) == 1
        # The rich record's data should have been merged
        assert result[0]["abstract"] == "Has abstract"

    def test_empty_list(self):
        from fetch_papers import deduplicate
        assert deduplicate([]) == []


# ---------------------------------------------------------------------------
# Unit tests: _ascii_slug()
# ---------------------------------------------------------------------------
class TestAsciiSlug:
    def test_basic_ascii(self):
        from fetch_papers import _ascii_slug
        assert _ascii_slug("Hello World") == "hello_world"

    def test_unicode_stripped(self):
        from fetch_papers import _ascii_slug
        result = _ascii_slug("Müller Straße")
        assert "muller" in result
        # Should not contain non-ASCII
        assert result.isascii()

    def test_special_characters_become_underscores(self):
        from fetch_papers import _ascii_slug
        result = _ascii_slug("ML: A (Great) Tool!")
        assert all(c.isalnum() or c == "_" for c in result)

    def test_empty_string(self):
        from fetch_papers import _ascii_slug
        assert _ascii_slug("") == ""

    def test_no_leading_trailing_underscores(self):
        from fetch_papers import _ascii_slug
        result = _ascii_slug("  --hello-- ")
        assert not result.startswith("_")
        assert not result.endswith("_")


# ---------------------------------------------------------------------------
# Unit tests: classify_journal()
# ---------------------------------------------------------------------------
class TestClassifyJournal:
    def test_nature_medicine(self):
        from fetch_papers import classify_journal
        assert classify_journal("Nature Medicine") == "nature_medicine"

    def test_jama_variant(self):
        from fetch_papers import classify_journal
        assert classify_journal("JAMA Internal Medicine") == "jama"

    def test_jama_standalone(self):
        from fetch_papers import classify_journal
        assert classify_journal("JAMA") == "jama"

    def test_lancet_digital_health(self):
        from fetch_papers import classify_journal
        assert classify_journal("The Lancet Digital Health") == "lancet_digital_health"

    def test_bmj_variant(self):
        from fetch_papers import classify_journal
        assert classify_journal("BMJ Open") == "bmj"

    def test_npj_digital_medicine(self):
        from fetch_papers import classify_journal
        assert classify_journal("npj Digital Medicine") == "npj_digital_medicine"

    def test_unknown_falls_back(self):
        from fetch_papers import classify_journal
        assert classify_journal("Some Obscure Journal of Stuff") == "specialist_journals"

    def test_empty_string_falls_back(self):
        from fetch_papers import classify_journal
        assert classify_journal("") == "specialist_journals"


# ---------------------------------------------------------------------------
# Unit tests: classify_disease()
# ---------------------------------------------------------------------------
class TestClassifyDisease:
    def test_oncology(self):
        from fetch_papers import classify_disease
        assert classify_disease("Predicting breast cancer recurrence", "", []) == "oncology"

    def test_cardiovascular(self):
        from fetch_papers import classify_disease
        assert classify_disease("Atrial fibrillation prediction", "", []) == "cardiovascular"

    def test_diabetes(self):
        from fetch_papers import classify_disease
        assert classify_disease("", "Type 2 diabetes mellitus glucose control", []) == "diabetes"

    def test_sepsis_icu(self):
        from fetch_papers import classify_disease
        assert classify_disease("Early sepsis prediction in the ICU", "", []) == "sepsis_icu"

    def test_kidney_disease(self):
        from fetch_papers import classify_disease
        assert classify_disease("Acute kidney injury prediction", "", []) == "kidney_disease"

    def test_mesh_terms_used(self):
        from fetch_papers import classify_disease
        result = classify_disease("Generic title", "", ["Neoplasms"])
        assert result == "oncology"

    def test_fallback_other(self):
        from fetch_papers import classify_disease
        assert classify_disease("Some generic ML paper", "methods comparison", []) == "other"

    def test_empty_inputs(self):
        from fetch_papers import classify_disease
        assert classify_disease("", "", []) == "other"
