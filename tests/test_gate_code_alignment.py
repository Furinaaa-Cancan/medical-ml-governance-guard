def test_validate_script_runs():
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "scripts/diagnostics/validate_gate_code_alignment.py"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0
    assert "Cross-validation summary" in r.stdout


def test_validate_script_help():
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "scripts/diagnostics/validate_gate_code_alignment.py", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0
    assert "usage" in (r.stdout + r.stderr).lower()
