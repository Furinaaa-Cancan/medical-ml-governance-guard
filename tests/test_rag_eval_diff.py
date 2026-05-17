"""W11-F5: tests for `scripts/rag/evals/run_eval.py` --diff flag fixes.

Covers three silent-failure risks W10-R4 flagged:
  1. --diff baseline missing must be loud (--diff-required → exit 2).
  2. Per-scenario id access must tolerate `scenario_id` alias.
  3. Diff section must echo baseline aggregate so compositional shifts
     (newly_evaluable + newly_zero mass) are visible.

These tests poke `_render_diff_section` and `main` directly to stay fast
and avoid the multi-minute scoring pass that the smoke tests in
`test_rag_run_eval.py` exercise.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_EVAL_PATH = REPO_ROOT / "scripts" / "rag" / "evals" / "run_eval.py"


def _load_run_eval():
    """Import run_eval.py as a module without forcing a full package import."""
    spec = importlib.util.spec_from_file_location(
        "run_eval_under_test", RUN_EVAL_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


run_eval = _load_run_eval()


def test_diff_required_errors_when_baseline_missing(tmp_path, capsys):
    """--diff-required + missing baseline → exit code 2 with stderr error."""
    missing = tmp_path / "definitely_not_here.json"
    assert not missing.exists()

    # Use a scenarios path that won't be reached (fail-fast before scoring).
    rc = run_eval.main(
        [
            "--diff",
            str(missing),
            "--diff-required",
        ]
    )
    assert rc == 2, f"expected exit 2 on missing required baseline, got {rc}"
    captured = capsys.readouterr()
    assert "diff-required" in captured.err or "could not be loaded" in captured.err


def test_diff_not_required_default_warns_only(tmp_path, capsys, monkeypatch):
    """Default --diff (without --diff-required) on missing path: warn, no exit 2.

    We can't easily run the full pipeline without ML deps, so we monkey-patch
    `load_scenarios` to return an empty list — that lets main() proceed past
    the missing-diff warning and reach a normal `return 0`.
    """
    missing = tmp_path / "definitely_not_here.json"
    out = tmp_path / "out.md"

    monkeypatch.setattr(run_eval, "load_scenarios", lambda _p: [])

    rc = run_eval.main(
        [
            "--diff",
            str(missing),
            "--output",
            str(out),
        ]
    )
    assert rc == 0, "expected exit 0 when --diff-required is NOT set"
    err = capsys.readouterr().err
    assert "warning" in err.lower()
    assert str(missing) in err


def test_diff_handles_scenario_id_alias():
    """Baseline rows keyed by `scenario_id` (not `id`) must not KeyError."""
    baseline_data = {
        "aggregate": {"mean_tag_precision_at_k": 0.42},
        "per_scenario": [
            {
                "scenario_id": "alpha",  # NOTE: alias, not "id"
                "tag_precision_at_k": 0.5,
            },
            {
                "scenario_id": "beta",
                "tag_precision_at_k": None,
            },
        ],
    }
    current = [
        {"id": "alpha", "tag_precision_at_k": 0.6},
        {"scenario_id": "beta", "tag_precision_at_k": 0.3},
        {"id": "gamma", "tag_precision_at_k": 0.1},  # missing from baseline
    ]

    # Must not raise KeyError.
    buf = io.StringIO()
    with redirect_stderr(buf):
        lines = run_eval._render_diff_section(current, baseline_data)

    text = "\n".join(lines)
    # alpha appears (matched), beta appears (newly evaluable: None → 0.3),
    # gamma is missing in baseline and reported in the trailing note.
    assert "`alpha`" in text
    assert "`beta`" in text
    assert "not present" in text or "excluded" in text


def test_diff_skips_row_without_any_id(capsys):
    """Rows lacking both id and scenario_id → stderr warn, no crash."""
    baseline_data = {
        "per_scenario": [
            {"tag_precision_at_k": 0.5},  # no id at all
            {"id": "ok", "tag_precision_at_k": 0.5},
        ],
    }
    current = [{"id": "ok", "tag_precision_at_k": 0.6}]

    buf = io.StringIO()
    with redirect_stderr(buf):
        run_eval._render_diff_section(current, baseline_data)
    assert "skipping row without id/scenario_id" in buf.getvalue()


def test_diff_echoes_baseline_aggregate():
    """Baseline aggregate metrics must appear above the per-scenario table."""
    baseline_data = {
        "aggregate": {
            "mean_precision_at_5": 0.612,
            "mean_top1_score": 0.789,
            "mean_tag_precision": 0.555,
        },
        "per_scenario": [
            {"id": "alpha", "tag_precision_at_k": 0.5},
        ],
    }
    current = [{"id": "alpha", "tag_precision_at_k": 0.6}]

    lines = run_eval._render_diff_section(current, baseline_data)
    text = "\n".join(lines)

    # The exact baseline numbers should be echoed so a reader can spot
    # compositional shifts at a glance.
    assert "0.612" in text, "mean_precision_at_5 should be echoed"
    assert "mean_precision_at_5" in text
    assert "mean_top1_score" in text
    assert "mean_tag_precision" in text

    # Aggregate echo must appear BEFORE the per-scenario table header.
    header_idx = text.index("| id | baseline P@K")
    echo_idx = text.index("Baseline aggregate")
    assert echo_idx < header_idx, "aggregate echo must precede the table"


def test_diff_echoes_canonical_aggregate_keys_too():
    """Should also surface the aggregate keys actually emitted by aggregate()."""
    baseline_data = {
        "aggregate": {
            "mean_tag_precision_at_k": 0.333,
            "mean_hit_at_k": 0.444,
            "coverage_rate": 0.71,
        },
        "per_scenario": [],
    }
    lines = run_eval._render_diff_section([], baseline_data)
    text = "\n".join(lines)
    assert "0.333" in text
    assert "mean_tag_precision_at_k" in text
    assert "mean_hit_at_k" in text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-x", "--tb=short"]))
