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
GATES_DIR = SCRIPTS_DIR / "gates"


# ────────────────────────────────────────────────────────
# Discover all gate scripts
# ────────────────────────────────────────────────────────

def _discover_gate_scripts() -> List[str]:
    """Return names of all *_gate.py scripts."""
    gates_dir = SCRIPTS_DIR / "gates"
    return sorted(
        p.stem for p in gates_dir.glob("*_gate.py")
        if not p.name.startswith("._") and not p.name.startswith("test_")
    )


def _discover_all_scripts_with_main() -> List[str]:
    """Return names of all scripts that define a main() function."""
    results = []
    for subdir in ["gates", "training", "reporting", "codebooks", "review", "diagnostics", "orchestration"]:
        for p in sorted((SCRIPTS_DIR / subdir).glob("*.py")):
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


def _find_script(name: str) -> Path:
    """Find a script by name across all subdirectories."""
    for subdir in ["gates", "training", "reporting", "codebooks", "review", "diagnostics", "orchestration"]:
        candidate = SCRIPTS_DIR / subdir / f"{name}.py"
        if candidate.exists():
            return candidate
    return SCRIPTS_DIR / f"{name}.py"  # fallback


# ────────────────────────────────────────────────────────
# Gate --help tests (every gate should accept --help)
# ────────────────────────────────────────────────────────

class TestGateHelpFlags:
    @pytest.mark.parametrize("gate_name", GATE_SCRIPTS)
    def test_gate_help_exits_zero(self, gate_name: str):
        """Every gate script should accept --help and exit 0."""
        script = GATES_DIR / f"{gate_name}.py"
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
        """Every script with main() must accept --help and emit argparse help.

        Originally this only checked that the return code was 0/1/2 (the
        latter to accommodate argparse usage errors and missing optional
        deps). That spec was too forgiving: a script with NO argparse at
        all also exits 0 — it just silently ignores --help and runs its
        body. Two distinct sessions (commits a1fd3a1 and f0a22a1) traced
        real damage to that loophole:

          - 5 diagnostic scripts hit the 30s subprocess timeout because
            their bodies cloned repos / hit network on --help.
          - merge_discovered_into_kb.py exited 0 fast but quietly wrote
            references/case-studies/peer-review-kb.json and rewrote
            paper/kb-merge-report.md on every pytest run, polluting state
            invisibly.

        Tightened spec: rc must be exactly 0 AND argparse must have
        printed its usage line ("usage:" appears in stdout or stderr).
        argparse always emits this on --help; running a body without
        argparse does not. This change closes the silently-passing
        loophole permanently — any new script added without an argparse
        guard fails CI immediately, with a clear error pointing at the
        fix (add `argparse.ArgumentParser(description=__doc__).parse_args()`
        at main()'s top).

        Missing-optional-deps cases (e.g., flask not installed for
        scripts/diagnostics/web UI) still exit 1 with no usage line, so
        we surface them too — they belong in requirements-optional.txt
        or behind a sentinel skip, not as silent CI green.
        """
        script = _find_script(script_name)
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True, text=True, timeout=30,
            env={**dict(__import__("os").environ), "PYTHONPATH": str(SCRIPTS_DIR)},
        )
        combined = (result.stdout or "") + (result.stderr or "")
        assert result.returncode == 0, (
            f"{script_name} --help did not exit 0 (rc={result.returncode}). "
            f"Stderr tail: {result.stderr[-500:]}"
        )
        assert "usage:" in combined.lower(), (
            f"{script_name} --help exited 0 but printed no argparse "
            f"`usage:` line — likely missing argparse and silently running "
            f"main() body. Add at top of main():\n"
            f"    argparse.ArgumentParser(description=__doc__).parse_args()\n"
            f"Output head: {combined[:300]!r}"
        )


# ────────────────────────────────────────────────────────
# Gate scripts with missing required args should exit non-zero
# ────────────────────────────────────────────────────────

class TestGateMissingArgs:
    @pytest.mark.slow
    @pytest.mark.parametrize("gate_name", GATE_SCRIPTS)
    def test_gate_no_args_exits_nonzero(self, gate_name: str):
        """Gate with no args should fail (exit 2) due to missing required params."""
        script = GATES_DIR / f"{gate_name}.py"
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
        script = GATES_DIR / f"{gate_name}.py"
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
        script = GATES_DIR / f"{gate_name}.py"
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
        script = GATES_DIR / f"{gate_name}.py"
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
        script = GATES_DIR / f"{gate_name}.py"
        content = script.read_text(encoding="utf-8")
        assert "\ndef main(" in content, f"{gate_name} missing main() function"

    @pytest.mark.parametrize("gate_name", GATE_SCRIPTS)
    def test_gate_has_name_guard(self, gate_name: str):
        """Every gate script should have if __name__ == '__main__' guard."""
        script = GATES_DIR / f"{gate_name}.py"
        content = script.read_text(encoding="utf-8")
        assert '__name__' in content and '__main__' in content, (
            f"{gate_name} missing __name__ == '__main__' guard"
        )
