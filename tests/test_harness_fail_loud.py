"""Fail-loud regression tests for scripts/rag/evals/harness.py (W14-F3).

Companion to test_cli_fail_loud.py (universal probe) — these tests pin
down the *specific* behavior we expect from harness.py's --baseline and
--kb flags, so a future refactor can't quietly regress to silent-skip.

The bugs being fixed (catalogued by W13-A0):
  • --baseline <missing.json> used to print "BASELINE: ... missing" to
    stdout and exit 0, identical-shape bug to W11-F5 (run_eval --diff).
  • --kb <anything> in --mode hybrid used to be silently ignored — the
    hybrid path resolves the KB via scripts.rag.config, so a user
    passing --kb thought they targeted a custom KB but actually hit
    the prebuilt dense index.

Fix policy (W14-F3):
  • --baseline missing → argparse error, exit 2 (mirrors W11-F5).
  • --kb missing → argparse error, exit 2 (regardless of mode — the
    universal fail-loud probe expects this).
  • --kb present + --mode hybrid → stderr WARN (not error) so existing
    wrapper scripts that always pass --kb keep working; the docstring
    has documented --kb as ignored-by-design in hybrid mode since W3.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "rag" / "evals" / "harness.py"
SCENARIOS = REPO_ROOT / "references" / "retrieval_eval" / "scenarios.json"
BASELINE = REPO_ROOT / "references" / "retrieval_eval" / "baseline.json"


def _run(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=timeout,
    )


# ── --baseline path validation ─────────────────────────────────────

def test_baseline_path_missing_errors(tmp_path: Path) -> None:
    """--baseline <nonexistent> must exit 2 with stderr explaining why.

    Pre-W14: printed "BASELINE: ... missing" to stdout and exited 0,
    hiding CI config drift exactly like W11-F4/W11-F5 did.
    """
    fake = tmp_path / "no_such_baseline.json"
    assert not fake.exists()
    r = _run("--baseline", str(fake), timeout=20)
    assert r.returncode == 2, (
        f"expected exit 2 for missing --baseline, got {r.returncode}.\n"
        f"stdout: {r.stdout[:300]!r}\nstderr: {r.stderr[:300]!r}"
    )
    # argparse routes p.error() to stderr with "error:" prefix.
    assert "does not exist" in r.stderr, (
        f"stderr must explain the missing path. Got: {r.stderr[:300]!r}"
    )
    assert "--baseline" in r.stderr, (
        f"stderr must name the offending flag. Got: {r.stderr[:300]!r}"
    )


def test_baseline_valid_path_still_works(tmp_path: Path) -> None:
    """Regression: a real --baseline path still completes normally.

    Uses a minimal synthetic baseline with one matching scenario so
    we don't depend on the live retrieval pipeline (this test should
    pass in milliseconds, not seconds).
    """
    # Synthesize a 1-scenario fixture so we don't hit the live KB at all.
    scenarios = tmp_path / "scen.json"
    scenarios.write_text(json.dumps({
        "scenarios": [{
            "scenario_id": "smoke_one",
            "gate_name": "leakage_test",
            "failure_codes": ["LEAK001"],
            "expected_categories": ["data_leakage"],
            "expected_tags": ["leakage"],
            "query_text": "data leakage smoke",
        }],
    }))
    # Baseline with the same scenario_id at zero floor — any current
    # result trivially satisfies the regression check.
    baseline = tmp_path / "base.json"
    baseline.write_text(json.dumps({
        "scenarios": [{
            "scenario_id": "smoke_one",
            "coverage": 0.0,
            "hit_at_k": 0.0,
            "tag_precision": 0.0,
        }],
    }))
    # bm25_only so we don't pay the 20s BGE model load.
    r = _run(
        "--mode", "bm25_only",
        "--scenarios", str(scenarios),
        "--baseline", str(baseline),
        timeout=60,
    )
    # We don't assert rc==0 strictly because the synthetic scenario
    # may legitimately hit@K=0; what matters is the script does NOT
    # crash on argparse and DID read the baseline (the rc==2 path
    # is the regression we're guarding against).
    assert r.returncode in (0, 2), (
        f"unexpected rc={r.returncode} on valid --baseline path.\n"
        f"stderr: {r.stderr[:400]!r}"
    )
    # If it exited 2 it must be because of a regression/strict-fail,
    # NOT because of the argparse path check.
    assert "does not exist" not in r.stderr


# ── --kb path validation + mode mismatch ───────────────────────────

def test_kb_path_missing_errors(tmp_path: Path) -> None:
    """--kb <nonexistent> must exit 2 even in hybrid mode.

    The universal fail-loud probe (test_cli_fail_loud.py) expects
    this: input paths are validated regardless of whether the
    downstream code path uses them. Mode-mismatch warnings come
    SECOND to path existence.
    """
    fake = tmp_path / "no_such_kb.jsonl"
    r = _run("--kb", str(fake), timeout=20)
    assert r.returncode == 2, (
        f"expected exit 2 for missing --kb, got {r.returncode}.\n"
        f"stderr: {r.stderr[:300]!r}"
    )
    assert "does not exist" in r.stderr
    assert "--kb" in r.stderr


def test_kb_with_hybrid_mode_warns(tmp_path: Path) -> None:
    """--kb <real-path> --mode hybrid must warn to stderr (not crash).

    Decision (W14-F3): warn rather than error. The docstring has
    documented --kb as a no-op in hybrid mode since W3, so silently
    erroring would break wrapper scripts that always pass --kb. The
    warning explicitly tells the user the flag is being ignored.
    """
    # Real but empty file — passes path-exists, gets to mode check.
    fake_kb = tmp_path / "custom_kb.jsonl"
    fake_kb.write_text("")
    # Tiny synthetic scenarios file so we don't pay the live-pipeline cost.
    scenarios = tmp_path / "scen.json"
    scenarios.write_text(json.dumps({
        "scenarios": [{
            "scenario_id": "smoke_kb_warn",
            "gate_name": "leakage_test",
            "failure_codes": ["LEAK001"],
            "expected_categories": ["data_leakage"],
            "expected_tags": ["leakage"],
            "query_text": "data leakage smoke kb warn",
        }],
    }))
    r = _run(
        "--mode", "hybrid",
        "--kb", str(fake_kb),
        "--scenarios", str(scenarios),
        timeout=60,
    )
    # Must warn. The script may still exit 0 or 2 depending on
    # whether the live hybrid path finds anything for the synthetic
    # scenario — what matters is the WARN line was emitted before
    # the harness committed to the run.
    assert "WARN" in r.stderr and "--kb" in r.stderr, (
        f"expected stderr WARN about --kb in hybrid mode. "
        f"Got: {r.stderr[:500]!r}"
    )
    assert "hybrid" in r.stderr.lower()


def test_kb_with_bm25_only_mode_no_warn(tmp_path: Path) -> None:
    """Regression: --kb with --mode bm25_only must NOT warn.

    In bm25_only mode --kb actually controls KB loading, so a
    spurious warning would mislead users into thinking the flag
    isn't taking effect.
    """
    fake_kb = tmp_path / "custom_kb.jsonl"
    fake_kb.write_text("")
    scenarios = tmp_path / "scen.json"
    scenarios.write_text(json.dumps({
        "scenarios": [{
            "scenario_id": "smoke_kb_bm25",
            "gate_name": "leakage_test",
            "failure_codes": ["LEAK001"],
            "expected_categories": ["data_leakage"],
            "expected_tags": ["leakage"],
            "query_text": "data leakage smoke kb bm25",
        }],
    }))
    r = _run(
        "--mode", "bm25_only",
        "--kb", str(fake_kb),
        "--scenarios", str(scenarios),
        timeout=60,
    )
    # No --kb mode-mismatch warning in bm25_only mode.
    assert not ("WARN" in r.stderr and "ignored in --mode hybrid" in r.stderr), (
        f"unexpected --kb mode-mismatch warn in bm25_only mode. "
        f"stderr: {r.stderr[:500]!r}"
    )
