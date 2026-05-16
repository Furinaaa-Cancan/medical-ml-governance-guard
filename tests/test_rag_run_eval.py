"""Smoke test for the reproducible eval script (Wave 4 A4)."""

import json
import subprocess
import sys

import pytest

pytest.importorskip("sentence_transformers")


def test_run_eval_help_exits_zero():
    r = subprocess.run(
        [sys.executable, "scripts/rag/evals/run_eval.py", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0
    assert "usage" in (r.stdout + r.stderr).lower()


def test_run_eval_produces_markdown_and_json(tmp_path):
    out = tmp_path / "eval.md"
    r = subprocess.run(
        [
            sys.executable,
            "scripts/rag/evals/run_eval.py",
            "--mode",
            "hybrid",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert out.exists()
    assert out.with_suffix(".json").exists()
    data = json.loads(out.with_suffix(".json").read_text())
    assert "aggregate" in data
    assert "per_scenario" in data
    assert isinstance(data["per_scenario"], list)
    assert data["aggregate"]["n_scenarios"] > 0


def test_run_eval_reports_hit_at_k_metric(tmp_path):
    """Wave 5 P2: hit@K should be the primary metric (A2 finding)."""
    out = tmp_path / "eval.md"
    subprocess.run(
        [sys.executable, "scripts/rag/evals/run_eval.py", "--output", str(out)],
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    data = json.loads(out.with_suffix(".json").read_text())
    agg = data["aggregate"]
    assert "mean_hit_at_k" in agg, "primary metric mean_hit_at_k missing"
    assert "coverage_rate" in agg, "coverage_rate missing (A4 ghost-improvement guard)"
    assert "n_evaluable" in agg


def test_run_eval_markdown_shows_hit_at_k_before_tag_precision(tmp_path):
    """Render order: hit@K first (primary), tag_precision second (secondary)."""
    out = tmp_path / "eval.md"
    subprocess.run(
        [sys.executable, "scripts/rag/evals/run_eval.py", "--output", str(out)],
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    md = out.read_text()
    hit_idx = md.find("hit@K")
    tp_idx = md.find("tag_precision")
    assert hit_idx > 0 and tp_idx > 0, "both metrics should appear"
    assert hit_idx < tp_idx, "hit@K should appear before tag_precision"
