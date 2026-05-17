"""Tests for scripts/diagnostics/lint_stderr_routing.py (W8-W3).

The lint catches the H7 + W7-P9 class of bugs: status-prefixed print()
calls that default to stdout when they should go to stderr (to avoid
polluting JSON output piped from CLI tools).

These tests pin the lint to the post-fix-clean surface (mlgg.py CLI).
The lint also surfaces 12 pre-existing violations in interactive/training
scripts; those are out of scope for W8-W3 (no source changes allowed)
and documented for follow-up tasks.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LINT = REPO / "scripts" / "diagnostics" / "lint_stderr_routing.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LINT), *args],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO),
    )


def test_lint_passes_on_mlgg_cli():
    """After H7 + W7-P9 fixes, lint must be clean on the mlgg CLI entrypoint."""
    r = _run("scripts/orchestration/mlgg.py")
    assert r.returncode == 0, (
        f"violations remain on mlgg.py (regression of H7/W7-P9):\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )


def test_lint_catches_planted_violation(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text('print("[FAIL] this should go to stderr")\n')
    r = _run(str(bad))
    assert r.returncode == 1
    assert "stderr-routing" in r.stderr
    assert "[FAIL]" in r.stderr


def test_lint_ignores_correct_print(tmp_path):
    good = tmp_path / "good.py"
    good.write_text(
        "import sys\nprint('[FAIL] correct', file=sys.stderr)\n"
    )
    r = _run(str(good))
    assert r.returncode == 0


def test_lint_detects_all_status_prefixes(tmp_path):
    """Every status prefix in the rule must be caught."""
    src = tmp_path / "many.py"
    src.write_text(
        "print('[FAIL] x')\n"
        "print('[WARN] x')\n"
        "print('[OK] x')\n"
        "print('[ERROR] x')\n"
        "print('[INFO] x')\n"
        "print('[DEBUG] x')\n"
        "print('[SKIP] x')\n"
        "print('$ echo hi')\n"
    )
    r = _run(str(src))
    assert r.returncode == 1
    # 8 violations, one per line
    assert r.stderr.count("stderr-routing") >= 1
    for prefix in ("[FAIL]", "[WARN]", "[OK]", "[ERROR]", "[INFO]",
                   "[DEBUG]", "[SKIP]", "$ "):
        assert prefix in r.stderr, f"prefix {prefix!r} not flagged"


def test_lint_skips_non_status_prints(tmp_path):
    """Plain print() with no status prefix is allowed."""
    src = tmp_path / "plain.py"
    src.write_text(
        "print('hello world')\n"
        "print(f'result: {42}')\n"
        "print('done')\n"
    )
    r = _run(str(src))
    assert r.returncode == 0


def test_lint_skips_tests_dir(tmp_path):
    """Files under a tests/ directory are exempt."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "t.py").write_text('print("[FAIL] in a test")\n')
    r = _run(str(tmp_path))
    assert r.returncode == 0, f"tests/ exemption failed: {r.stderr}"


def test_lint_handles_syntax_error_gracefully(tmp_path):
    """Files with SyntaxError don't crash the lint."""
    bad = tmp_path / "broken.py"
    bad.write_text("def (oops:\n  pass\n")
    r = _run(str(bad))
    # SyntaxError yields no violations, exit 0
    assert r.returncode == 0


def test_lint_handles_non_utf8_gracefully(tmp_path):
    """Files that aren't UTF-8 are skipped without crashing."""
    bad = tmp_path / "binary.py"
    bad.write_bytes(b"# encoding test\n\xb0\xb1\xb2\n")
    r = _run(str(bad))
    assert r.returncode == 0


def test_lint_non_py_files_skipped(tmp_path):
    """Non-.py files are not scanned even if they look like code."""
    f = tmp_path / "script.sh"
    f.write_text('print("[FAIL] not python")\n')
    r = _run(str(f))
    assert r.returncode == 0


def test_lint_kwarg_other_than_stderr_still_violates(tmp_path):
    """file=sys.stdout (explicit) still counts as a violation."""
    src = tmp_path / "x.py"
    src.write_text(
        "import sys\nprint('[FAIL] explicit stdout', file=sys.stdout)\n"
    )
    r = _run(str(src))
    assert r.returncode == 1
