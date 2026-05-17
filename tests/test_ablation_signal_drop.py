"""Coverage tests for ``scripts/rag/evals/ablation_signal_drop.py`` (W14-C1).

The script's existing smoke (``test_ablation_smoke.py``) only verifies
``--help``. The real diagnostic logic (config patching, weight rebalancing,
markdown rendering, JSON output) was 0% covered per W13-V1. If the W11-I1
ablation silently regresses, the next ablation-driven decision (the kind
that drove W13-P0's DENSE_WEIGHT rebalance) would use wrong data.

These tests monkeypatch ``harness.evaluate_scenario`` with a deterministic
stub that mirrors the production return shape but pays NO BGE-load cost.
The stub returns metrics that depend on the patched config so we can
verify the ablation modes actually differ (the most important invariant
— if hybrid_no_dense and hybrid_all produce identical numbers, the
config patching is broken and the diagnostic is silently useless).

A single end-to-end ``@pytest.mark.slow`` test invokes the real harness
against a tiny 1-scenario fixture so the contract between the ablation
script and the real retrieval stack is also exercised, but skipped in
``-m "not slow"`` CI runs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "rag" / "evals" / "ablation_signal_drop.py"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _tiny_scenarios_blob() -> Dict[str, Any]:
    """A minimal scenarios.json payload (3 scenarios) the harness can read."""
    return {
        "version": "test-1.0",
        "description": "W14-C1 ablation test fixture (tiny, in-memory).",
        "scenarios": [
            {
                "scenario_id": "t1",
                "description": "tiny scenario 1",
                "gate_name": "leakage_gate",
                "failure_codes": ["target_leakage"],
                "expected_categories": ["data_leakage"],
                "expected_tags": ["target_leakage", "temporal_leakage"],
                "query_text": "target leakage in features",
            },
            {
                "scenario_id": "t2",
                "description": "tiny scenario 2",
                "gate_name": "evaluation_quality_gate",
                "failure_codes": ["improper_primary_metric"],
                "expected_categories": ["evaluation_metrics"],
                "expected_tags": ["missing_calibration", "incomplete_metrics"],
                "query_text": "macro F1 reported as primary metric",
            },
            {
                "scenario_id": "t3",
                "description": "tiny scenario 3",
                "gate_name": "external_validation_gate",
                "failure_codes": ["no_external_validation"],
                "expected_categories": ["external_validation"],
                "expected_tags": ["no_external_validation"],
                "query_text": "single-center development without external test",
            },
        ],
    }


@pytest.fixture()
def tiny_scenarios_path(tmp_path: Path) -> Path:
    """Write the tiny scenarios blob to ``tmp_path`` and return its path."""
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps(_tiny_scenarios_blob(), indent=2), encoding="utf-8")
    return path


def _stub_evaluate_scenario_factory(call_log: List[Dict[str, Any]]):
    """Return a deterministic stub of ``harness.evaluate_scenario``.

    The stub reads ``scripts.rag.config.WEIGHT_DENSE`` / ``WEIGHT_BM25`` /
    ``WEIGHT_TAG_OVERLAP`` / ``WEIGHT_SEVERITY`` / ``MMR_LAMBDA`` at call
    time so the values reflect any active ``_patched_config`` overrides.
    Each scenario produces a tag_precision that depends on:

      * mode (bm25_only is the "best" control)
      * config weights (so different ablation modes yield different numbers)

    This is the *whole point*: if the script's patching does not actually
    propagate to the harness call, the test for mode-differences will
    fail loudly.
    """
    import importlib

    def _stub(scenario, *, top_k=5, mode="hybrid", **kwargs):  # noqa: ANN001
        cfg = importlib.import_module("scripts.rag.config")
        # Snapshot the config state visible at call time, so tests can
        # introspect what the script actually patched per call.
        snapshot = {
            "WEIGHT_DENSE": cfg.WEIGHT_DENSE,
            "WEIGHT_BM25": cfg.WEIGHT_BM25,
            "WEIGHT_TAG_OVERLAP": cfg.WEIGHT_TAG_OVERLAP,
            "WEIGHT_SEVERITY": cfg.WEIGHT_SEVERITY,
            "MMR_LAMBDA": cfg.MMR_LAMBDA,
        }
        call_log.append(
            {
                "scenario_id": scenario["scenario_id"],
                "mode": mode,
                "top_k": top_k,
                "config": snapshot,
            }
        )

        # Deterministic, mode-sensitive metrics:
        # bm25_only is the strongest control; hybrid configurations vary
        # by their patched weights so ablation deltas are non-zero.
        if mode == "bm25_only":
            tag_p = 0.80
            cov = 1.0
            hit = 1.0
        else:
            # Hybrid: precision tracks the proportion of NON-dense weight
            # (since dense was the dilutor per W11-I1, killing it should
            # raise precision; this matches the real ablation finding).
            non_dense = (
                snapshot["WEIGHT_BM25"]
                + snapshot["WEIGHT_TAG_OVERLAP"]
                + snapshot["WEIGHT_SEVERITY"]
            )
            tag_p = round(0.4 + 0.4 * non_dense, 4)
            cov = 1.0 if non_dense >= 0.3 else 0.5
            hit = 1.0
            # Encode MMR effect so hybrid_no_mmr also differs from hybrid_all.
            if snapshot["MMR_LAMBDA"] >= 1.0:
                tag_p = round(tag_p + 0.05, 4)

        return {
            "scenario_id": scenario["scenario_id"],
            "description": scenario.get("description", ""),
            "gate_name": scenario.get("gate_name", ""),
            "mode": mode,
            "retrieved_count": top_k,
            "coverage": cov,
            "hit_at_k": hit,
            "tag_precision": tag_p,
            "matched_expected_categories": [],
            "matched_expected_tags": [],
            "top_k_summary": [],
        }

    return _stub


@pytest.fixture()
def stub_harness(monkeypatch):
    """Replace ``harness.evaluate_scenario`` with a deterministic stub.

    Returns the per-call log so tests can inspect what config the script
    actually passed in for each call.
    """
    from scripts.rag.evals import harness as harness_mod

    call_log: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        harness_mod, "evaluate_scenario",
        _stub_evaluate_scenario_factory(call_log),
    )
    return call_log


# ---------------------------------------------------------------------------
# 1. Smoke: --help
# ---------------------------------------------------------------------------


def test_help_exits_clean() -> None:
    """``--help`` exits 0 and mentions ablation. (Duplicated from
    test_ablation_smoke for coverage attribution to this test file.)"""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage:" in proc.stdout.lower()
    assert "ablation" in proc.stdout.lower()


# ---------------------------------------------------------------------------
# 2. parse_args defaults + overrides
# ---------------------------------------------------------------------------


def test_parse_args_defaults(tmp_path: Path) -> None:
    from scripts.rag.evals.ablation_signal_drop import (
        parse_args, DEFAULT_SCENARIOS, DEFAULT_MD_OUT, DEFAULT_JSON_OUT,
        DEFAULT_TOP_K,
    )

    ns = parse_args([])
    assert ns.scenarios == DEFAULT_SCENARIOS
    assert ns.md_out == DEFAULT_MD_OUT
    assert ns.json_out == DEFAULT_JSON_OUT
    assert ns.top_k == DEFAULT_TOP_K
    assert ns.quiet is False


def test_parse_args_overrides(tmp_path: Path) -> None:
    from scripts.rag.evals.ablation_signal_drop import parse_args

    md = tmp_path / "out.md"
    js = tmp_path / "out.json"
    sc = tmp_path / "scen.json"
    ns = parse_args([
        "--scenarios", str(sc),
        "--md-out", str(md),
        "--json-out", str(js),
        "--top-k", "3",
        "--quiet",
    ])
    assert ns.scenarios == sc
    assert ns.md_out == md
    assert ns.json_out == js
    assert ns.top_k == 3
    assert ns.quiet is True


# ---------------------------------------------------------------------------
# 3. _patched_config — applies + restores; handles missing attrs
# ---------------------------------------------------------------------------


def test_patched_config_restores_originals() -> None:
    import importlib
    from scripts.rag.evals.ablation_signal_drop import _patched_config

    cfg = importlib.import_module("scripts.rag.config")
    orig_dense = cfg.WEIGHT_DENSE
    with _patched_config({"WEIGHT_DENSE": 0.999}):
        assert cfg.WEIGHT_DENSE == 0.999
    assert cfg.WEIGHT_DENSE == orig_dense


def test_patched_config_restores_on_exception() -> None:
    import importlib
    from scripts.rag.evals.ablation_signal_drop import _patched_config

    cfg = importlib.import_module("scripts.rag.config")
    orig = cfg.WEIGHT_BM25
    with pytest.raises(RuntimeError):
        with _patched_config({"WEIGHT_BM25": 0.123}):
            assert cfg.WEIGHT_BM25 == 0.123
            raise RuntimeError("bang")
    assert cfg.WEIGHT_BM25 == orig


def test_patched_config_handles_missing_attribute() -> None:
    """Adding a brand-new attribute should be deleted on exit, not restored."""
    import importlib
    from scripts.rag.evals.ablation_signal_drop import _patched_config

    cfg = importlib.import_module("scripts.rag.config")
    assert not hasattr(cfg, "_W14_C1_TEMP_ATTR")
    with _patched_config({"_W14_C1_TEMP_ATTR": 42}):
        assert cfg._W14_C1_TEMP_ATTR == 42
    assert not hasattr(cfg, "_W14_C1_TEMP_ATTR")


# ---------------------------------------------------------------------------
# 4. _build_configurations — 6 entries, weights re-balance to 1.0
# ---------------------------------------------------------------------------


def test_build_configurations_shape() -> None:
    from scripts.rag.evals.ablation_signal_drop import _build_configurations

    configs = _build_configurations()
    assert len(configs) == 6
    labels = [c[0] for c in configs]
    assert labels == [
        "A_bm25_only",
        "B_hybrid_all",
        "C_hybrid_no_dense",
        "D_hybrid_no_tag",
        "E_hybrid_no_sev",
        "F_hybrid_no_mmr",
    ]
    # First two have no overrides; others must override at least one knob.
    assert configs[0][2] == {}
    assert configs[1][2] == {}
    for _label, _mode, ov in configs[2:]:
        assert ov, f"expected non-empty overrides, got {ov}"


def test_rebalanced_weights_sum_to_one() -> None:
    """For each hybrid_minus_* config the four weight keys should sum to 1.0."""
    from scripts.rag.evals.ablation_signal_drop import _build_configurations

    weight_keys = {
        "WEIGHT_DENSE", "WEIGHT_BM25", "WEIGHT_TAG_OVERLAP", "WEIGHT_SEVERITY",
    }
    for label, _mode, ov in _build_configurations():
        if label in ("A_bm25_only", "B_hybrid_all", "F_hybrid_no_mmr"):
            continue
        present = {k: v for k, v in ov.items() if k in weight_keys}
        assert weight_keys.issubset(present.keys()), (
            f"{label} missing weight keys: {weight_keys - present.keys()}"
        )
        total = sum(present.values())
        assert abs(total - 1.0) < 1e-9, f"{label} weights sum to {total}, not 1.0"


def test_no_mmr_overrides_disable_diversity() -> None:
    """``F_hybrid_no_mmr`` must set MMR_LAMBDA >= 1.0 (passthrough branch)."""
    from scripts.rag.evals.ablation_signal_drop import _build_configurations

    by_label = {c[0]: c[2] for c in _build_configurations()}
    ov = by_label["F_hybrid_no_mmr"]
    assert ov["MMR_LAMBDA"] >= 1.0
    assert ov["MMR_COSINE_FLOOR"] > 1.0  # belt-and-braces


# ---------------------------------------------------------------------------
# 5. _format_markdown — table structure
# ---------------------------------------------------------------------------


def test_format_markdown_includes_all_rows() -> None:
    from scripts.rag.evals.ablation_signal_drop import _format_markdown

    results = [
        {
            "config": "A_bm25_only", "mode": "bm25_only", "overrides": {},
            "total_scenarios": 3,
            "mean_tag_precision_at_5": 0.80,
            "coverage_rate": 1.0, "hit_at_k_rate": 1.0,
            "per_scenario": [],
        },
        {
            "config": "B_hybrid_all", "mode": "hybrid", "overrides": {},
            "total_scenarios": 3,
            "mean_tag_precision_at_5": 0.50,
            "coverage_rate": 1.0, "hit_at_k_rate": 1.0,
            "per_scenario": [],
        },
        {
            "config": "C_hybrid_no_dense", "mode": "hybrid", "overrides": {},
            "total_scenarios": 3,
            "mean_tag_precision_at_5": 0.75,
            "coverage_rate": 1.0, "hit_at_k_rate": 1.0,
            "per_scenario": [],
        },
    ]
    md = _format_markdown(results)
    assert "W11-I1" in md
    assert "A_bm25_only" in md
    assert "B_hybrid_all" in md
    assert "C_hybrid_no_dense" in md
    # delta column heading
    assert "delta_vs_bm25" in md
    assert "delta_vs_hybrid_all" in md
    # Reading guide present
    assert "Reading the table" in md


# ---------------------------------------------------------------------------
# 6. main() — full run end-to-end with stubbed harness
# ---------------------------------------------------------------------------


def test_main_writes_json_and_md(
    tmp_path: Path, tiny_scenarios_path: Path, stub_harness, capsys,
) -> None:
    """End-to-end: main() reads scenarios, calls (stubbed) harness 6x per
    scenario, writes parseable JSON + markdown, exits 0."""
    from scripts.rag.evals.ablation_signal_drop import main

    md_out = tmp_path / "report.md"
    json_out = tmp_path / "report.json"

    rc = main([
        "--scenarios", str(tiny_scenarios_path),
        "--md-out", str(md_out),
        "--json-out", str(json_out),
        "--quiet",
    ])
    assert rc == 0
    assert md_out.exists()
    assert json_out.exists()

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["top_k"] == 5
    assert len(payload["results"]) == 6  # 6 ablation configurations
    # 3 scenarios in fixture × 6 configurations = 18 stubbed harness calls
    assert len(stub_harness) == 18

    # Each result has required keys
    for r in payload["results"]:
        assert "config" in r
        assert "mode" in r
        assert "mean_tag_precision_at_5" in r
        assert "coverage_rate" in r
        assert "hit_at_k_rate" in r
        assert "per_scenario" in r
        assert len(r["per_scenario"]) == 3

    md_text = md_out.read_text(encoding="utf-8")
    assert "A_bm25_only" in md_text
    assert "F_hybrid_no_mmr" in md_text


def test_main_modes_actually_differ(
    tmp_path: Path, tiny_scenarios_path: Path, stub_harness,
) -> None:
    """Ablation modes must produce DIFFERENT numbers from hybrid_all.

    This is the load-bearing invariant. If hybrid_no_dense == hybrid_all,
    either ``_patched_config`` is broken or the config knobs are not being
    read at call time, and the diagnostic is silently useless. (The stub
    deliberately makes precision depend on the dense weight so this fires
    if patching ever stops working.)
    """
    from scripts.rag.evals.ablation_signal_drop import main

    md_out = tmp_path / "report.md"
    json_out = tmp_path / "report.json"
    rc = main([
        "--scenarios", str(tiny_scenarios_path),
        "--md-out", str(md_out),
        "--json-out", str(json_out),
        "--quiet",
    ])
    assert rc == 0

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    by_label = {r["config"]: r for r in payload["results"]}
    hybrid_all = by_label["B_hybrid_all"]["mean_tag_precision_at_5"]
    hybrid_no_dense = by_label["C_hybrid_no_dense"]["mean_tag_precision_at_5"]
    hybrid_no_mmr = by_label["F_hybrid_no_mmr"]["mean_tag_precision_at_5"]
    bm25_only = by_label["A_bm25_only"]["mean_tag_precision_at_5"]

    assert hybrid_no_dense != hybrid_all, (
        "ablation broken: hybrid_no_dense == hybrid_all (config patch did "
        "not propagate to the harness call)"
    )
    assert hybrid_no_mmr != hybrid_all, (
        "MMR ablation broken: F_hybrid_no_mmr == B_hybrid_all"
    )
    # bm25_only should differ from hybrid_all too.
    assert bm25_only != hybrid_all


def test_main_reproducible(
    tmp_path: Path, tiny_scenarios_path: Path, monkeypatch,
) -> None:
    """Same input + same code = same JSON output (no nondeterminism)."""
    # Two independent runs each get a fresh stub + log.
    def _run(out_dir: Path) -> Dict[str, Any]:
        from scripts.rag.evals import harness as harness_mod
        from scripts.rag.evals.ablation_signal_drop import main

        call_log: List[Dict[str, Any]] = []
        monkeypatch.setattr(
            harness_mod, "evaluate_scenario",
            _stub_evaluate_scenario_factory(call_log),
        )
        md = out_dir / "report.md"
        js = out_dir / "report.json"
        rc = main([
            "--scenarios", str(tiny_scenarios_path),
            "--md-out", str(md),
            "--json-out", str(js),
            "--quiet",
        ])
        assert rc == 0
        return json.loads(js.read_text(encoding="utf-8"))

    out_a = tmp_path / "a"; out_a.mkdir()
    out_b = tmp_path / "b"; out_b.mkdir()

    a = _run(out_a)
    b = _run(out_b)

    # Compare the metrics (ignore scenarios_file path which differs by run dir).
    a_results = [
        (r["config"], r["mean_tag_precision_at_5"], r["coverage_rate"], r["hit_at_k_rate"])
        for r in a["results"]
    ]
    b_results = [
        (r["config"], r["mean_tag_precision_at_5"], r["coverage_rate"], r["hit_at_k_rate"])
        for r in b["results"]
    ]
    assert a_results == b_results


def test_main_quiet_suppresses_per_config_stderr(
    tmp_path: Path, tiny_scenarios_path: Path, stub_harness, capsys,
) -> None:
    from scripts.rag.evals.ablation_signal_drop import main

    md_out = tmp_path / "report.md"
    json_out = tmp_path / "report.json"
    rc = main([
        "--scenarios", str(tiny_scenarios_path),
        "--md-out", str(md_out), "--json-out", str(json_out),
        "--quiet",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    # --quiet suppresses the per-config "[ablation] ..." stderr lines.
    assert "[ablation] A_bm25_only" not in err


def test_main_verbose_emits_per_config_stderr(
    tmp_path: Path, tiny_scenarios_path: Path, stub_harness, capsys,
) -> None:
    from scripts.rag.evals.ablation_signal_drop import main

    md_out = tmp_path / "report.md"
    json_out = tmp_path / "report.json"
    rc = main([
        "--scenarios", str(tiny_scenarios_path),
        "--md-out", str(md_out), "--json-out", str(json_out),
    ])
    assert rc == 0
    err = capsys.readouterr().err
    # Without --quiet, we should see the per-config progress lines.
    assert "[ablation]" in err
    assert "A_bm25_only" in err


# ---------------------------------------------------------------------------
# 7. Error paths
# ---------------------------------------------------------------------------


def test_main_returns_2_on_missing_scenarios_file(
    tmp_path: Path, stub_harness, capsys,
) -> None:
    from scripts.rag.evals.ablation_signal_drop import main

    missing = tmp_path / "nope.json"
    rc = main([
        "--scenarios", str(missing),
        "--md-out", str(tmp_path / "m.md"),
        "--json-out", str(tmp_path / "j.json"),
        "--quiet",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "scenarios file not found" in err


def test_main_returns_2_on_empty_scenarios_list(
    tmp_path: Path, stub_harness, capsys,
) -> None:
    from scripts.rag.evals.ablation_signal_drop import main

    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"scenarios": []}), encoding="utf-8")
    rc = main([
        "--scenarios", str(p),
        "--md-out", str(tmp_path / "m.md"),
        "--json-out", str(tmp_path / "j.json"),
        "--quiet",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "empty" in err.lower()


# ---------------------------------------------------------------------------
# 8. SLOW: real harness end-to-end (skipped in -m "not slow")
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_main_against_real_harness_one_scenario(tmp_path: Path) -> None:
    """End-to-end against the REAL harness on a single fixture scenario.

    Pays the BGE-model load cost; only intended for the slow CI lane. The
    point is to keep the ablation script's contract with the real
    retrieval stack under test without requiring it for every PR.
    """
    from scripts.rag.evals.ablation_signal_drop import main

    # Use just one scenario to keep wall time as low as possible while
    # still proving the real retrieval path returns sensible numbers.
    blob = {
        "version": "test",
        "description": "slow lane",
        "scenarios": [_tiny_scenarios_blob()["scenarios"][0]],
    }
    sc = tmp_path / "scen.json"
    sc.write_text(json.dumps(blob), encoding="utf-8")

    md_out = tmp_path / "m.md"
    json_out = tmp_path / "j.json"
    rc = main([
        "--scenarios", str(sc),
        "--md-out", str(md_out),
        "--json-out", str(json_out),
        "--quiet",
    ])
    assert rc == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert len(payload["results"]) == 6
    # Every result must have a finite mean_tag_precision in [0, 1].
    for r in payload["results"]:
        p5 = r["mean_tag_precision_at_5"]
        assert 0.0 <= p5 <= 1.0
