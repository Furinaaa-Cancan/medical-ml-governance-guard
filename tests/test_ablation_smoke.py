"""Smoke test for the W11-I1 signal-ablation diagnostic.

The full ablation runs six hybrid configurations against 30 scenarios with
sentence-transformer embeddings — far too heavy for a smoke test. We just
verify the script's CLI parses cleanly and ``--help`` exits with rc=0, which
catches argparse / import-time breakage without paying the BGE load cost.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "rag" / "evals" / "ablation_signal_drop.py"


def test_ablation_script_help_exits_clean() -> None:
    """`ablation_signal_drop.py --help` must exit 0 and mention the script."""
    assert SCRIPT.exists(), f"ablation script missing at {SCRIPT}"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, (
        f"--help exited {proc.returncode}\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    # argparse always prints "usage:" — guard against the script's
    # description being silently dropped by a future refactor.
    assert "usage:" in proc.stdout.lower()
    assert "ablation" in proc.stdout.lower()
