"""Tests for scripts/review/peer_review_lookup.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


class TestCLI:
    """Test the CLI interface of peer_review_lookup.py."""

    def _run(self, args: list) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(SCRIPTS_DIR / "review/peer_review_lookup.py")] + args
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_help_exits_zero(self):
        result = self._run(["--help"])
        assert result.returncode == 0
        assert "Query Peer Review Knowledge Base" in result.stdout

    def test_no_args_shows_help(self):
        result = self._run([])
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower() or "Query" in result.stdout

    def test_stats(self):
        result = self._run(["--stats"])
        assert result.returncode == 0
        assert "Papers:" in result.stdout
        assert "Concerns:" in result.stdout

    def test_query_by_gate(self):
        result = self._run(["--gate", "leakage_gate"])
        assert result.returncode == 0
        assert "Gate: leakage_gate" in result.stdout

    def test_query_by_dimension(self):
        result = self._run(["--dimension", "1"])
        assert result.returncode == 0
        assert "Dimension 1" in result.stdout

    def test_query_by_tags(self):
        result = self._run(["--tags", "no_external_validation"])
        assert result.returncode == 0
        assert "Tags:" in result.stdout

    def test_query_by_category(self):
        result = self._run(["--category", "evaluation_metrics"])
        assert result.returncode == 0
        assert "Category:" in result.stdout

    def test_query_by_search(self):
        result = self._run(["--search", "calibration"])
        assert result.returncode == 0
        assert "Text search:" in result.stdout

    def test_severity_filter(self):
        result = self._run(["--gate", "leakage_gate", "--severity", "CRITICAL"])
        assert result.returncode == 0

    def test_limit(self):
        result = self._run(["--gate", "leakage_gate", "--limit", "2"])
        assert result.returncode == 0

    def test_invalid_dimension(self):
        result = self._run(["--dimension", "99"])
        assert result.returncode == 0  # doesn't crash, just returns no results
        assert "Results: 0" in result.stdout
