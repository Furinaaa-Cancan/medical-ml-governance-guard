"""Tests for R030 — verdict-path NaN bypass detection (W20-F3, W15-A3).

W15-A3 finding: ``scripts/gates/calibration_dca_gate.py`` and
``scripts/gates/external_validation_gate.py`` use raw
``float(metric) > float(threshold)`` in fail decisions. NaN → comparison
False → gate passes garbage. R030 must flag these (and only these)
patterns inside ``scripts/gates/``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mlgg_lint.ast_utils import TaintTracker, build_import_map
from mlgg_lint.engine import analyze_file
from mlgg_lint.models import Severity
from mlgg_lint.rules.r030_nan_bypass import NanBypassInVerdict


REPO = Path(__file__).resolve().parents[1]


# ── unit helpers ─────────────────────────────────────────────────────────

def _run_rule_on_source(src: str, display_path: str) -> list:
    """Parse ``src`` and run R030 against it as if it lived at
    ``display_path``. Bypasses the engine so we can isolate the rule."""
    tree = ast.parse(src)
    im = build_import_map(tree)
    rule = NanBypassInVerdict(
        file_path=display_path,
        import_map=im,
        taint_tracker=TaintTracker(),
    )
    return rule.check(tree)


# ── TRUE POSITIVE: the W15-A3 pattern ────────────────────────────────────

def test_flags_float_gt_threshold_in_gate_file():
    src = "if float(metric) > float(threshold):\n    fail()\n"
    diags = _run_rule_on_source(src, "scripts/gates/sample_gate.py")
    assert len(diags) == 1
    assert diags[0].rule_id == "R030"
    assert diags[0].severity == Severity.ERROR


def test_flags_float_lt_in_chained_comparison():
    """Chained comparison: ``lo < float(metric) < hi``."""
    src = "if 0.0 < float(metric) < 1.0:\n    pass\n"
    diags = _run_rule_on_source(src, "scripts/gates/sample_gate.py")
    assert len(diags) == 1


def test_flags_abs_wrapped_float_call():
    src = "if abs(float(intercept)) > float(thresh):\n    fail()\n"
    diags = _run_rule_on_source(src, "scripts/gates/sample_gate.py")
    # abs() wraps the inner float() — both LHS (via abs) and RHS are flagged.
    assert len(diags) == 1


def test_flags_float_subtraction_in_compare():
    """W15-A3 external_validation_gate.py:545 — ``float(np.max(x)) -
    float(np.min(x)) > 1e-9``. NaN-NaN=NaN, NaN > eps = False = bypass."""
    src = (
        "import numpy as np\n"
        "if float(np.max(x)) - float(np.min(x)) > 1e-9:\n"
        "    fail()\n"
    )
    diags = _run_rule_on_source(src, "scripts/gates/sample_gate.py")
    assert len(diags) == 1


def test_flags_each_compare_once_even_with_both_sides_floated():
    src = (
        "if float(a) > float(b):\n"
        "    fail()\n"
        "if float(c) < float(d):\n"
        "    fail()\n"
    )
    diags = _run_rule_on_source(src, "scripts/gates/sample_gate.py")
    # Two Compare nodes → two diagnostics, not four.
    assert len(diags) == 2


# ── TRUE NEGATIVE: things R030 must NOT flag ─────────────────────────────

def test_does_not_flag_float_of_literal_constant():
    """``float(0.5)`` cannot be NaN — should not fire."""
    src = "if float(0.5) > x:\n    pass\n"
    diags = _run_rule_on_source(src, "scripts/gates/sample_gate.py")
    assert diags == []


def test_does_not_flag_float_of_string_literal():
    """``float('0.5')`` is parse-time constant — also safe."""
    src = "if float('0.5') > x:\n    pass\n"
    diags = _run_rule_on_source(src, "scripts/gates/sample_gate.py")
    assert diags == []


def test_does_not_flag_to_float_call():
    """``to_float(x)`` is the W15-A3-recommended safe wrapper."""
    src = "if to_float(metric) > to_float(threshold):\n    fail()\n"
    diags = _run_rule_on_source(src, "scripts/gates/sample_gate.py")
    assert diags == []


def test_does_not_flag_numpy_float_coercion():
    """``np.float64(x)`` is out-of-scope (per R030 docstring)."""
    src = (
        "import numpy as np\n"
        "if np.float64(x) > threshold:\n"
        "    fail()\n"
    )
    diags = _run_rule_on_source(src, "scripts/gates/sample_gate.py")
    assert diags == []


def test_does_not_flag_outside_gates_scope():
    """Same float(x) > y pattern in a diagnostics file is NOT flagged.

    Serialization sites legitimately use float() to coerce values into
    JSON-safe form without taking pass/fail decisions on the result.
    """
    src = "if float(metric) > float(threshold):\n    fail()\n"
    diags = _run_rule_on_source(src, "scripts/diagnostics/sample_diag.py")
    assert diags == []


def test_does_not_flag_in_module_root_path():
    """Random scripts outside scripts/gates/ are also out of scope."""
    src = "if float(a) > b:\n    pass\n"
    diags = _run_rule_on_source(src, "tools/random_helper.py")
    assert diags == []


def test_skips_non_compare_float_calls():
    """``y = float(x)`` (Assign, no Compare) is not a verdict bypass."""
    src = "y = float(metric)\nz = float(x) + 1\n"
    diags = _run_rule_on_source(src, "scripts/gates/sample_gate.py")
    assert diags == []


def test_argparse_type_float_is_not_a_compare():
    """``argparse.add_argument(..., type=float)`` uses float as a *callable*,
    not in a Compare — so it's structurally invisible to R030."""
    src = (
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--thresh', type=float)\n"
    )
    diags = _run_rule_on_source(src, "scripts/gates/sample_gate.py")
    assert diags == []


def test_identity_op_not_flagged():
    """``float(x) is None`` is structurally a Compare but Is/IsNot are
    not numeric ops — verdict-bypass doesn't apply."""
    src = "if float(x) is None:\n    pass\n"  # silly but legal
    diags = _run_rule_on_source(src, "scripts/gates/sample_gate.py")
    assert diags == []


# ── INTEGRATION: hits the real W15-A3 sites ──────────────────────────────

@pytest.mark.parametrize(
    "gate_file, min_expected_hits",
    [
        # W15-A3 cites lines 582, 589, 601, 672-673 in calibration_dca_gate.
        # Counting per-Compare-node: 582, 589 (x3 chained), 601, 672, 673
        # collapse to 4 distinct Compare nodes (one diag each).
        ("scripts/gates/calibration_dca_gate.py", 3),
        # W15-A3 cites lines 177, 545 in external_validation_gate (plus
        # extra bona-fide sites the rule surfaces in the same file).
        ("scripts/gates/external_validation_gate.py", 2),
    ],
)
def test_catches_w15_a3_sites(gate_file, min_expected_hits):
    """R030 must catch at least the W15-A3-reported NaN-bypass sites."""
    path = REPO / gate_file
    assert path.exists(), f"missing gate file under audit: {path}"
    diags = analyze_file(path)
    r030 = [d for d in diags if d.rule_id == "R030"]
    assert len(r030) >= min_expected_hits, (
        f"expected >= {min_expected_hits} R030 hits in {gate_file}, "
        f"got {len(r030)}; lines={[d.location.line for d in r030]}"
    )


def test_does_not_flood_diagnostics_directory():
    """False-positive bound: a sample of scripts/diagnostics/ should
    produce 0 R030 hits, because the rule is gate-scoped."""
    diag_dir = REPO / "scripts" / "diagnostics"
    if not diag_dir.exists():
        pytest.skip("scripts/diagnostics/ not present")
    sample = sorted(diag_dir.glob("*.py"))[:10]
    total = 0
    for p in sample:
        diags = analyze_file(p)
        total += sum(1 for d in diags if d.rule_id == "R030")
    assert total == 0, f"R030 leaked into diagnostics/: {total} hits"
