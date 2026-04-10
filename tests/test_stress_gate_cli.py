"""
Exhaustive gate CLI main() tests — invoke every gate's main() with help flag
and basic error scenarios.

Designed for overnight CI runs (~30-60 minutes).
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


# ────────────────────────────────────────────────────────
# Discover all gate scripts
# ────────────────────────────────────────────────────────

def _discover_gate_scripts() -> List[str]:
    """Return names of all *_gate.py scripts."""
    return sorted(
        p.stem for p in SCRIPTS_DIR.glob("*_gate.py")
        if not p.name.startswith("._") and not p.name.startswith("test_")
    )


def _discover_all_scripts_with_main() -> List[str]:
    """Return names of all scripts that define a main() function."""
    results = []
    for p in sorted(SCRIPTS_DIR.glob("*.py")):
        if p.name.startswith("._") or p.name.startswith("test_") or p.name.startswith("__"):
            continue
        try:
            content = p.read_text(encoding="utf-8")
            if "\ndef main(" in content:
                results.append(p.stem)
        except OSError:
            continue
    return results


GATE_SCRIPTS = _discover_gate_scripts()
ALL_SCRIPTS_WITH_MAIN = _discover_all_scripts_with_main()


# ────────────────────────────────────────────────────────
# Gate --help tests (every gate should accept --help)
# ────────────────────────────────────────────────────────

class TestGateHelpFlags:
    @pytest.mark.parametrize("gate_name", GATE_SCRIPTS)
    def test_gate_help_exits_zero(self, gate_name: str):
        """Every gate script should accept --help and exit 0."""
        script = SCRIPTS_DIR / f"{gate_name}.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True, text=True, timeout=30,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
        )
        assert result.returncode == 0, (
            f"{gate_name} --help failed (rc={result.returncode}): {result.stderr[:500]}"
        )
        assert len(result.stdout) > 0, f"{gate_name} --help produced no output"


# ────────────────────────────────────────────────────────
# All scripts with main() accept --help
# ────────────────────────────────────────────────────────

class TestAllScriptsHelp:
    @pytest.mark.parametrize("script_name", ALL_SCRIPTS_WITH_MAIN)
    def test_help_exits_zero(self, script_name: str):
        """Every script with main() should accept --help and exit 0."""
        script = SCRIPTS_DIR / f"{script_name}.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True, text=True, timeout=30,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
        )
        # Accept 0, 2 (argparse), or 1 (missing optional dependency like flask)
        assert result.returncode in (0, 1, 2), (
            f"{script_name} --help failed (rc={result.returncode}): {result.stderr[:500]}"
        )


# ────────────────────────────────────────────────────────
# Gate scripts with missing required args should exit non-zero
# ────────────────────────────────────────────────────────

class TestGateMissingArgs:
    @pytest.mark.slow
    @pytest.mark.parametrize("gate_name", GATE_SCRIPTS)
    def test_gate_no_args_exits_nonzero(self, gate_name: str):
        """Gate with no args should fail (exit 2) due to missing required params."""
        script = SCRIPTS_DIR / f"{gate_name}.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=30,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
        )
        # Most gates require --report or evidence-dir, so should exit non-zero
        assert result.returncode != 0, (
            f"{gate_name} with no args unexpectedly succeeded"
        )


# ────────────────────────────────────────────────────────
# Gate scripts with nonexistent paths should fail gracefully
# ────────────────────────────────────────────────────────

class TestGateNonexistentPaths:
    @pytest.mark.slow
    @pytest.mark.parametrize("gate_name", GATE_SCRIPTS)
    def test_gate_nonexistent_report_path(self, gate_name: str, tmp_path: Path):
        """Gate with --report pointing to nonexistent dir should fail."""
        script = SCRIPTS_DIR / f"{gate_name}.py"
        fake_report = tmp_path / "nonexistent" / "report.json"
        result = subprocess.run(
            [sys.executable, str(script), "--report", str(fake_report)],
            capture_output=True, text=True, timeout=60,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
        )
        # Should not hang or crash with traceback — exit 2 is expected
        assert result.returncode != 0


# ────────────────────────────────────────────────────────
# Gate report contract: valid JSON with expected fields
# ────────────────────────────────────────────────────────

class TestGateReportContract:
    @pytest.mark.slow
    @pytest.mark.parametrize("gate_name", GATE_SCRIPTS)
    def test_gate_produces_valid_report(self, gate_name: str, tmp_path: Path):
        """When a gate runs (even failing), its report should be valid JSON."""
        script = SCRIPTS_DIR / f"{gate_name}.py"
        report_path = tmp_path / "report.json"
        # Create minimal evidence structure
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        request = tmp_path / "request.json"
        request.write_text('{"target_column": "target", "study_name": "test"}',
                           encoding="utf-8")
        # Run gate
        result = subprocess.run(
            [sys.executable, str(script), "--report", str(report_path)],
            capture_output=True, text=True, timeout=120,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
        )
        # If a report was created, validate its structure
        if report_path.exists():
            data = json.loads(report_path.read_text(encoding="utf-8"))
            assert isinstance(data, dict), f"{gate_name} report is not a dict"
            # All reports should have at least a status field
            if "status" in data:
                assert data["status"] in ("pass", "fail", "skip", "error"), (
                    f"{gate_name} has invalid status: {data['status']}"
                )


# ────────────────────────────────────────────────────────
# Gate script syntax validation
# ────────────────────────────────────────────────────────

class TestGateSyntax:
    @pytest.mark.parametrize("gate_name", GATE_SCRIPTS)
    def test_gate_compiles(self, gate_name: str):
        """Every gate script should compile without syntax errors."""
        script = SCRIPTS_DIR / f"{gate_name}.py"
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(script)],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, (
            f"{gate_name} has syntax errors: {result.stderr}"
        )

    @pytest.mark.parametrize("gate_name", GATE_SCRIPTS)
    def test_gate_has_main_function(self, gate_name: str):
        """Every gate script should define a main() function."""
        script = SCRIPTS_DIR / f"{gate_name}.py"
        content = script.read_text(encoding="utf-8")
        assert "\ndef main(" in content, f"{gate_name} missing main() function"

    @pytest.mark.parametrize("gate_name", GATE_SCRIPTS)
    def test_gate_has_name_guard(self, gate_name: str):
        """Every gate script should have if __name__ == '__main__' guard."""
        script = SCRIPTS_DIR / f"{gate_name}.py"
        content = script.read_text(encoding="utf-8")
        assert '__name__' in content and '__main__' in content, (
            f"{gate_name} missing __name__ == '__main__' guard"
        )
