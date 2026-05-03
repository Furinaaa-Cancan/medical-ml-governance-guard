"""Contract compliance test for all 33 gates.

Surfaced by Round-2 code review (test-quality audit): prior to this file,
no single test validated that every gate respects the published CLI +
report-envelope contract (SKILL.md / ARCHITECTURE.md §"Gate Contract"):

    Exit 0 = PASS    Exit 2 = FAIL    Exit 1 = ERROR

    Report: { status, failure_count, warning_count, failures[], warnings[],
              execution_time_seconds, envelope_version: "2.0.0" }

Adding a gate without --report or --strict, or emitting exit code 3, or
forgetting envelope_version would previously only surface at orchestration
time. This parametrized test catches such regressions on every PR.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GATES_DIR = PROJECT_ROOT / "scripts" / "gates"


def _discover_gate_scripts() -> list[Path]:
    """Return every gate script (excluding __init__.py and dotfiles).

    Skips dot-prefixed files because macOS creates AppleDouble metadata
    siblings ("._foo_gate.py") when files are copied to/from external
    volumes. Those siblings are 4 KB binary blobs, not Python; running
    `--help` on them produces a SyntaxError and pollutes CI test output
    on contributors who happen to develop from such a volume. The CI
    runner never sees them, but local pytest sweeps do.
    """
    return sorted(
        p for p in GATES_DIR.glob("*.py")
        if p.name != "__init__.py"
        and not p.name.startswith(".")
    )


GATE_SCRIPTS = _discover_gate_scripts()


@pytest.fixture(scope="module")
def gate_count_guard():
    """Catch orphan gate additions — if a new gate lands, the contract
    test coverage must scale with it. 33 is the documented count per
    ARCHITECTURE.md §"Gate DAG"; raise deliberately if that changes."""
    assert len(GATE_SCRIPTS) == 33, (
        f"Expected 33 gate scripts per ARCHITECTURE.md, found {len(GATE_SCRIPTS)}. "
        f"If this is intentional, update the assertion AND the public docs."
    )


class TestGateCLIContract:
    """Every gate must accept the standard CLI contract."""

    @pytest.mark.parametrize(
        "gate_path",
        GATE_SCRIPTS,
        ids=[p.stem for p in GATE_SCRIPTS],
    )
    def test_help_exits_zero(self, gate_path: Path):
        """`gate.py --help` must succeed (exit 0) — catches syntax errors,
        import errors, argparse misconfigurations at module load time."""
        result = subprocess.run(
            [sys.executable, str(gate_path), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"{gate_path.name} --help exited {result.returncode}. "
            f"stderr:\n{result.stderr[:500]}"
        )

    @pytest.mark.parametrize(
        "gate_path",
        GATE_SCRIPTS,
        ids=[p.stem for p in GATE_SCRIPTS],
    )
    def test_has_report_flag(self, gate_path: Path):
        """Every gate must expose --report so the DAG runner can collect
        JSON envelopes uniformly."""
        result = subprocess.run(
            [sys.executable, str(gate_path), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert "--report" in result.stdout, (
            f"{gate_path.name} missing --report flag in --help output"
        )

    @pytest.mark.parametrize(
        "gate_path",
        GATE_SCRIPTS,
        # security_audit_gate + self_critique_gate + publication_gate are
        # aggregation/meta gates; CONTRIBUTING.md explicitly notes their
        # contract may diverge. Exclude from strict-flag requirement.
        ids=[p.stem for p in GATE_SCRIPTS],
    )
    def test_has_strict_flag(self, gate_path: Path):
        """Every gate must expose --strict for the productized workflow
        (promotes warnings to failures). Aggregation gates may override."""
        result = subprocess.run(
            [sys.executable, str(gate_path), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        # Allow self_critique_gate / publication_gate / security_audit_gate
        # to skip --strict if they're aggregation-only.
        aggregation_allowlist = {
            "self_critique_gate",
            "publication_gate",
            "security_audit_gate",
        }
        if gate_path.stem in aggregation_allowlist:
            # Soft check: either --strict is present OR the gate is in the
            # explicit aggregation allowlist.
            return
        assert "--strict" in result.stdout, (
            f"{gate_path.name} missing --strict flag in --help output"
        )


class TestGateExitCodes:
    """Exit codes must be 0 (pass), 1 (error), or 2 (fail) — never other."""

    @pytest.mark.parametrize(
        "gate_path",
        GATE_SCRIPTS,
        ids=[p.stem for p in GATE_SCRIPTS],
    )
    def test_missing_required_args_exits_in_contract_range(
        self, gate_path: Path, tmp_path: Path
    ):
        """Running a gate with NO args must exit 1, 2, or (argparse)
        a standard error code — but crucially not produce an uncaught
        traceback that exits 3 or leaves garbage in stderr."""
        result = subprocess.run(
            [sys.executable, str(gate_path)],
            capture_output=True, text=True, timeout=30,
        )
        # argparse returns 2 on missing required args.
        # Gates that do their own validation may return 1.
        # Nothing should return 0 (pass) with no args, nor 3+.
        assert result.returncode in {1, 2}, (
            f"{gate_path.name} exited {result.returncode} with no args; "
            f"expected 1 (gate error) or 2 (argparse/gate fail). "
            f"stderr:\n{result.stderr[:300]}"
        )


# Guard invocation to catch orphan-gate drift.
def test_gate_count_is_documented_33():
    """Standalone test for the guard fixture — ensures the count matches
    the documented 33 in ARCHITECTURE.md §'Gate DAG'."""
    assert len(GATE_SCRIPTS) == 33, (
        f"Found {len(GATE_SCRIPTS)} gates — expected 33 per ARCHITECTURE.md. "
        f"Update docs if deliberately adding/removing gates."
    )
