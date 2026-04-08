"""Tests for the peer_review_lookup.py CLI tool."""

import subprocess
import sys
from pathlib import Path

import pytest

TOOL_PATH = str(Path(__file__).resolve().parents[1] / "scripts" / "tools" / "peer_review_lookup.py")


def _run(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run the CLI tool as a subprocess and return the result."""
    return subprocess.run(
        [sys.executable, TOOL_PATH, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class TestCLIHelp:
    """--help should exit 0 and show usage."""

    def test_help_exits_zero(self):
        result = _run("--help")
        assert result.returncode == 0

    def test_help_shows_description(self):
        result = _run("--help")
        assert "Query Peer Review Knowledge Base" in result.stdout


class TestCLIStats:
    """--stats should exit 0 and print statistics."""

    def test_stats_exits_zero(self):
        result = _run("--stats")
        assert result.returncode == 0

    def test_stats_prints_papers_count(self):
        result = _run("--stats")
        assert "Papers:" in result.stdout

    def test_stats_prints_concerns_count(self):
        result = _run("--stats")
        assert "Concerns:" in result.stdout

    def test_stats_prints_resolution_rate(self):
        result = _run("--stats")
        assert "Resolution Rate:" in result.stdout


class TestQueryByDimension:
    """--dimension should return results for valid dimensions."""

    def test_dimension_exits_zero(self):
        result = _run("--dimension", "2")
        assert result.returncode == 0

    def test_dimension_shows_query_title(self):
        result = _run("--dimension", "2")
        assert "Dimension 2" in result.stdout

    def test_dimension_shows_results_count(self):
        result = _run("--dimension", "5", "--limit", "3")
        assert "Results:" in result.stdout


class TestQueryByText:
    """--search should return results for text queries."""

    def test_search_exits_zero(self):
        result = _run("--search", "leakage")
        assert result.returncode == 0

    def test_search_shows_query_title(self):
        result = _run("--search", "calibration")
        assert "Text search:" in result.stdout

    def test_search_shows_results_count(self):
        result = _run("--search", "calibration", "--limit", "2")
        assert "Results:" in result.stdout


class TestOutputFormat:
    """Output should be readable text, not raw JSON."""

    def test_stats_output_is_not_json(self):
        result = _run("--stats")
        # Stats output uses box-drawing characters, not JSON braces
        assert "Papers:" in result.stdout

    def test_query_output_is_readable(self):
        result = _run("--dimension", "1", "--limit", "1")
        # Should contain human-readable query header
        assert "Query:" in result.stdout

    def test_no_args_shows_help(self):
        result = _run()
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower() or "usage:" in result.stderr.lower()
