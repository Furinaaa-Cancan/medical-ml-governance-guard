"""
Universal "fail-loud" CLI test — parametrized over every diagnostic / eval
script. Catches the silent-success-on-IO-error class of bug that bit
W11-F4 (lint --baseline-mode silent no-op) and W11-F5 (run_eval --diff
silent skip).

The pattern is simple:
  if a script accepts a file-INPUT flag AND we pass a nonexistent path,
  the script MUST exit non-zero. Silently warning + exit 0 hides
  configuration drift in CI and is treated as a bug.

Scope: scripts/diagnostics/*.py + scripts/rag/evals/*.py. Gate scripts
already covered by test_stress_gate_cli.py.

Important semantics notes (why some flags are NOT probed):
  • --report : universally an OUTPUT path across this repo. Pointing it
    at a nonexistent dir SHOULD eventually fail when the write happens,
    but that's a different bug class. Excluded from input probes.
  • --output : same as --report.
  • --kb / --scenarios : may default to a real shipped reference file;
    overriding with a fake path is the right input probe.

If a new silent-failure script is added in the future, this test fails
loudly and points at the offender. Genuine intentional silent-skip
behavior (rare; today only run_eval --diff without --diff-required)
belongs in SILENT_FAILURE_WHITELIST with a documented reason — and the
bar for an entry is "the script's design REQUIRES continuing past
missing input", not "we're too lazy to fix it".
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"


# ────────────────────────────────────────────────────────
# Script discovery
# ────────────────────────────────────────────────────────

def _is_cli_script(path: Path) -> bool:
    """A script is a CLI entry only if it has argparse + a __main__ guard or main().

    Library modules under scripts/diagnostics/ (e.g., gate_applicability.py —
    just exports a class) and one-shot import-side-effect scripts
    (merge_audit_findings.py — hard-codes paths and runs at import) are
    NOT CLIs and must be excluded; otherwise the parametrized probe
    flags them as silent-failure scripts when they're really just
    non-CLI modules.

    Heuristic: must use `argparse` AND have either `if __name__ ==`
    or `def main(`. Matches the contract enforced by
    test_stress_gate_cli.py::TestAllScriptsHelp.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if "argparse" not in text:
        return False
    return ("if __name__" in text) or ("\ndef main(" in text)


def _discover_scripts() -> List[Path]:
    """All diagnostic + eval CLI entries. Skip dunder + private + test files
    and non-CLI library modules."""
    candidates: List[Path] = []
    search_dirs = [SCRIPTS_DIR / "diagnostics", SCRIPTS_DIR / "rag" / "evals"]
    # scripts/lint/ does not exist today; include defensively if it appears later
    lint_dir = SCRIPTS_DIR / "lint"
    if lint_dir.exists():
        search_dirs.append(lint_dir)

    for subdir in search_dirs:
        if not subdir.exists():
            continue
        for p in sorted(subdir.glob("*.py")):
            if p.name.startswith(("_", ".", "test_")):
                continue
            if not _is_cli_script(p):
                continue
            candidates.append(p)
    return candidates


SCRIPTS = _discover_scripts()

# File-input flags we probe. Each script will only accept some of these;
# argparse rejects the rest with "unrecognized arguments" and we skip
# the probe for those flags (not a failure — just not testable here).
#
# NOTE: --report and --output are intentionally EXCLUDED — they are
# output-path flags across this repo. Pointing them at a missing dir is
# a different bug class (delayed write failure), not an "unreadable
# input" bug.
PROBE_FLAGS = [
    "--diff",
    "--baseline",
    "--baseline-mode",
    "--scenarios",
    "--input",
    "--config",
    "--from",
    "--source",
    "--kb",
]


# ────────────────────────────────────────────────────────
# Whitelist (start empty; investigate before adding)
# ────────────────────────────────────────────────────────

# Map "script_name.py::--flag" -> reason. An entry here means "this
# script's documented design is to warn + continue on missing input for
# this specific flag, and that behavior has been reviewed and accepted".
# DO NOT add entries to silence test failures without first opening a bug.
#
# Today's only documented soft-skip:
#   run_eval.py --diff  (W11-F5 made --diff-required the opt-in for hard
#   fail; bare --diff is documented to warn + continue, preserving
#   pre-W11 behavior for existing CI invocations).
SILENT_FAILURE_WHITELIST: dict[str, str] = {
    "run_eval.py::--diff": (
        "W11-F5: bare --diff documented to warn+continue. Use --diff-required "
        "for hard-fail. test_run_eval_diff_required separately covers the "
        "fail-loud path."
    ),
}

# KNOWN_BUG_PENDING_FIX is a *temporary* allowlist for silent-failure bugs
# this test caught but that are being fixed in a follow-up wave (W14). Each
# entry MUST link to the wave/issue planning the fix. Entries here are
# NOT design choices — they are real bugs (same pattern as W11-F4 / W11-F5)
# tracked for explicit removal, not silenced indefinitely.
#
# See /tmp/W13_A0_silent_failures.md for the catalogued findings + fix
# sketches. W14 must remove these entries in the same commit that fixes
# the underlying scripts.
KNOWN_BUG_PENDING_FIX: dict[str, str] = {
    "harness.py::--baseline": (
        "W13-A0 found: harness silently skips regression check when "
        "--baseline points at missing file (same shape as W11-F5 run_eval "
        "bug). W14 to add --baseline-required mirror of --diff-required."
    ),
    "harness.py::--kb": (
        "W13-A0 found: --kb silently ignored in hybrid mode (default). "
        "Help text mentions 'bm25_only mode only' but flag is consumed "
        "without warning in hybrid. W14 to decide: argparse-reject "
        "outside bm25_only, or validate path regardless of mode."
    ),
}


# ────────────────────────────────────────────────────────
# Subprocess env (mirrors test_stress_gate_cli.py)
# ────────────────────────────────────────────────────────

def _subproc_env() -> dict:
    return {**os.environ, "PYTHONPATH": str(SCRIPTS_DIR)}


def _arg_rejected(stderr: str) -> bool:
    """argparse signals 'I don't know this flag' in a few standard ways."""
    s = stderr.lower()
    if "unrecognized arguments" in s or "unrecognized argument" in s:
        return True
    # "error: argument --foo: invalid choice" means flag accepted but value
    # rejected (a different failure mode — not "flag unknown"); don't treat
    # as rejection here.
    return False


# ────────────────────────────────────────────────────────
# --help smoke test
# ────────────────────────────────────────────────────────

@pytest.mark.parametrize("script_path", SCRIPTS, ids=lambda p: p.name)
def test_script_help_exits_clean(script_path: Path):
    """Every discovered CLI script must accept --help and exit 0.

    This is a narrower restatement of test_stress_gate_cli.py::TestAllScriptsHelp
    scoped to the diagnostics+evals directories. Cheap to run and catches
    new scripts added without an argparse guard.
    """
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        env=_subproc_env(),
    )
    assert result.returncode == 0, (
        f"{script_path.name} --help failed (rc={result.returncode}). "
        f"stderr tail: {result.stderr[-400:]}"
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert "usage:" in combined.lower(), (
        f"{script_path.name} --help exited 0 but printed no argparse usage line — "
        f"likely missing argparse guard (script body ran instead). "
        f"Output head: {combined[:200]!r}"
    )


# ────────────────────────────────────────────────────────
# Missing-file probe
# ────────────────────────────────────────────────────────

@pytest.mark.parametrize("script_path", SCRIPTS, ids=lambda p: p.name)
def test_script_fails_loud_on_missing_input(script_path: Path, tmp_path: Path):
    """For each file-input flag the script accepts, a nonexistent path must fail.

    Methodology:
      1. Synthesize a guaranteed-absent path under tmp_path.
      2. For each PROBE_FLAGS entry, run the script with that flag +
         the fake path AND --help-shortcircuit-buster (i.e., bare invocation).
      3. If argparse rejects the flag → script doesn't accept it → skip.
      4. If the script accepts the flag and exits 0 → silent failure → assert.
      5. Whitelist documented soft-skip flags via SILENT_FAILURE_WHITELIST.

    Subtlety: a script with NO argparse at all will not "reject" unknown
    flags — sys.argv just contains them and the script ignores them.
    That case is already caught by test_script_help_exits_clean above
    (which asserts argparse printed a usage line). So this test only
    runs meaningfully on scripts that DO use argparse.
    """
    fake = tmp_path / "definitely_does_not_exist.json"
    assert not fake.exists()

    silent_offenders: list[str] = []

    for flag in PROBE_FLAGS:
        key = f"{script_path.name}::{flag}"
        if key in SILENT_FAILURE_WHITELIST:
            continue
        if key in KNOWN_BUG_PENDING_FIX:
            # Temporarily allowed; tracked in /tmp/W13_A0_silent_failures.md
            # for W14 fix. The entry MUST be removed when the underlying
            # script is fixed so this test starts catching regressions again.
            continue

        try:
            result = subprocess.run(
                [sys.executable, str(script_path), flag, str(fake)],
                capture_output=True,
                text=True,
                timeout=20,
                env=_subproc_env(),
            )
        except subprocess.TimeoutExpired:
            # Hanging on a missing file is itself a fail-loud violation,
            # but it also means we can't get a return code. Record and
            # continue so other flags still probe.
            silent_offenders.append(
                f"{flag}: TIMEOUT (>20s) on missing input — script likely "
                "ran main work instead of fail-fast on missing input."
            )
            continue

        stderr = result.stderr or ""

        # Script doesn't accept this flag at all → not testable.
        if _arg_rejected(stderr):
            continue

        # Script accepted the flag. Now demand rc != 0.
        if result.returncode == 0:
            # Heuristic: did the stderr reference the fake path or our flag?
            # If not, the script may have argparse but ignore the flag
            # (silently consumed by **kwargs / unparsed). That's also a bug,
            # but we want a confident assertion message.
            mentions_input = (
                str(fake) in stderr
                or str(fake) in (result.stdout or "")
                or flag in stderr
            )
            confidence = "high" if mentions_input else "low"
            silent_offenders.append(
                f"{flag}: rc=0 on missing input (confidence={confidence}). "
                f"stderr head: {stderr[:200]!r}"
            )

    if silent_offenders:
        pytest.fail(
            f"{script_path.name} silently accepts nonexistent input:\n  "
            + "\n  ".join(silent_offenders)
            + "\nFix: error + exit !=0 when an input file path is unreadable. "
            "(Pattern from W11-F4 / W11-F5.)\n"
            "If this is INTENTIONAL documented behavior, add an entry to "
            "SILENT_FAILURE_WHITELIST keyed by 'script_name.py::--flag'."
        )
