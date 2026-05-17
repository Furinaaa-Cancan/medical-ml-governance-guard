"""W9-D2: tests for lint_kb_tags.py (KB tag vocabulary lint).

W11-F4: added baseline-mode error-handling + --write-baseline tests.
"""
import json
import subprocess
import sys


def test_lint_runs_in_warn_mode():
    r = subprocess.run(
        [sys.executable, "scripts/diagnostics/lint_kb_tags.py"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0  # WARN-only
    assert "Total unique tags" in r.stdout


def test_lint_help_exits_clean():
    r = subprocess.run(
        [sys.executable, "scripts/diagnostics/lint_kb_tags.py", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0
    assert "usage" in (r.stdout + r.stderr).lower()


def test_strict_mode_fails_on_existing_legacy():
    """Confirms strict mode does what it claims (existing legacy IS violation)."""
    r = subprocess.run(
        [sys.executable, "scripts/diagnostics/lint_kb_tags.py", "--strict"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 1  # KB has known legacy violations


def test_baseline_mode_errors_when_file_missing(tmp_path):
    """W11-F4: --baseline-mode with a missing file must exit 2 (argparse error),
    NOT silently fall through to WARN-only exit 0 (the W10-R3 CI footgun)."""
    missing = tmp_path / "does_not_exist.json"
    r = subprocess.run(
        [sys.executable, "scripts/diagnostics/lint_kb_tags.py",
         "--baseline-mode", str(missing)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 2, (
        f"expected exit 2 (argparse error) for missing baseline, "
        f"got {r.returncode}; stderr={r.stderr!r}"
    )
    assert "does not exist" in r.stderr
    assert "--write-baseline" in r.stderr


def test_write_baseline_creates_file(tmp_path):
    """W11-F4: --write-baseline writes parseable JSON with singletons + narrowings."""
    out = tmp_path / "baseline.json"
    r = subprocess.run(
        [sys.executable, "scripts/diagnostics/lint_kb_tags.py",
         "--write-baseline", str(out)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    assert out.exists()
    payload = json.loads(out.read_text())
    assert "singletons" in payload
    assert "narrowings" in payload
    assert isinstance(payload["singletons"], list)
    assert isinstance(payload["narrowings"], list)


def test_baseline_mode_passes_when_no_new_violations(tmp_path):
    """W11-F4: writing then immediately reading baseline yields exit 0 (no NEW)."""
    baseline = tmp_path / "baseline.json"
    w = subprocess.run(
        [sys.executable, "scripts/diagnostics/lint_kb_tags.py",
         "--write-baseline", str(baseline)],
        capture_output=True, text=True, timeout=30,
    )
    assert w.returncode == 0
    r = subprocess.run(
        [sys.executable, "scripts/diagnostics/lint_kb_tags.py",
         "--baseline-mode", str(baseline)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, (
        f"expected exit 0 when baseline matches current state, "
        f"got {r.returncode}; stdout={r.stdout!r}"
    )
    assert "No new violations" in r.stdout
