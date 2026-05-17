"""W9-D2: tests for lint_kb_tags.py (KB tag vocabulary lint)."""


def test_lint_runs_in_warn_mode():
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "scripts/diagnostics/lint_kb_tags.py"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0  # WARN-only
    assert "Total unique tags" in r.stdout


def test_lint_help_exits_clean():
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "scripts/diagnostics/lint_kb_tags.py", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0
    assert "usage" in (r.stdout + r.stderr).lower()


def test_strict_mode_fails_on_existing_legacy():
    """Confirms strict mode does what it claims (existing legacy IS violation)."""
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "scripts/diagnostics/lint_kb_tags.py", "--strict"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 1  # KB has known legacy violations
