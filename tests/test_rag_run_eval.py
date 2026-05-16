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


def test_score_one_synthesizes_query_when_query_text_missing(monkeypatch):
    """W7-P1: a scenario with gate + codes but no query_text must still
    trigger retrieval.

    Pre-fix, run_eval.py passed the empty string to rag_query, which
    short-circuits to [] regardless of gate/codes; this silently dropped
    15/30 scenarios from the post-Wave-5 baseline (n_hits=0, wall_ms=0).
    The harness path (scripts/rag/evals/harness.py) already synthesizes a
    "gate code1 code2" query in that case; this test pins run_eval.py to
    the same behaviour so the two harnesses cannot drift.
    """
    from scripts.rag.evals import run_eval

    captured: dict = {}

    def fake_rag_query(query, *, gate=None, failure_codes=None, top_k=5):
        captured["query"] = query
        captured["gate"] = gate
        captured["failure_codes"] = failure_codes
        return []

    # Patch the module rag_query imports lazily.
    import scripts.rag as rag_pkg
    monkeypatch.setattr(rag_pkg, "rag_query", fake_rag_query, raising=False)

    scenario = {
        "scenario_id": "no_query_text_synth_check",
        "gate_name": "evaluation_quality_gate",
        "failure_codes": ["improper_primary_metric", "missing_calibration_metric"],
        "expected_tags": ["evaluation_metrics"],
        "query_text": "",
    }
    result = run_eval.score_one(scenario, mode="hybrid", top_k=5)

    # The synthesized query must be non-empty and mention the gate.
    assert captured["query"].strip(), (
        "score_one passed empty query to rag_query; synthesis fallback failed"
    )
    assert "evaluation_quality_gate" in captured["query"]
    assert "improper_primary_metric" in captured["query"]
    # Gate + codes must still be forwarded for the gate filter / tag boost.
    assert captured["gate"] == "evaluation_quality_gate"
    assert captured["failure_codes"] == [
        "improper_primary_metric",
        "missing_calibration_metric",
    ]
    # n_hits is 0 here because we faked rag_query; the point is that retrieval
    # was *attempted*, not bypassed.
    assert result["n_hits"] == 0
    assert result["id"] == "no_query_text_synth_check"


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
