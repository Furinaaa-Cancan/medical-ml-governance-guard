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
