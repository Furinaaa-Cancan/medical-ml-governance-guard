"""Tests for scripts/rag/evals/run_ncpr_benchmark.py (W22-X6).

Covers the orchestrator wiring + stub-fallback path. Real sibling
module logic (X1..X5) is tested in their own files; here we only
exercise that the orchestrator calls them in the right order, adapts
their output schemas, and that the stub fallbacks honour the contract.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.rag.evals import run_ncpr_benchmark as orch  # noqa: E402


SCRIPT = REPO_ROOT / "scripts" / "rag" / "evals" / "run_ncpr_benchmark.py"


# ── CLI ──────────────────────────────────────────────────────────────────────


class TestCli:
    def test_help_exits_zero(self):
        """--help must exit 0 — basic sanity that argparse is wired."""
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode == 0, r.stderr
        assert "NCPR-Bench" in r.stdout
        for flag in ("--holdout", "--max-papers", "--rag-only", "--top-k"):
            assert flag in r.stdout

    def test_main_max_papers_zero_smoke(self, tmp_path):
        """`main()` with --max-papers 0 returns empty results.

        Smoke test: orchestrator must survive a zero-paper run without
        invoking the SUT so a holdout file can be sanity-checked before
        a full RAG sweep.
        """
        holdout = tmp_path / "holdout.json"
        holdout.write_text(json.dumps({
            "papers": [
                {"paper_id": "PR-001", "paper_doi": "10.1/a"},
                {"paper_id": "PR-002", "paper_doi": "10.1/b"},
            ],
        }))
        kb = tmp_path / "kb.json"
        kb.write_text(json.dumps({"entries": []}))

        out_json = tmp_path / "out.json"
        out_md = tmp_path / "out.md"

        rc = orch.main([
            "--holdout", str(holdout),
            "--output", str(out_json),
            "--report", str(out_md),
            "--max-papers", "0",
            "--kb", str(kb),
        ])
        assert rc == 0
        assert out_json.exists()
        assert out_md.exists()

        result = json.loads(out_json.read_text())
        assert result["schema_version"] == "ncpr-bench-v1"
        assert result["n_papers_evaluated"] == 0
        assert result["per_paper"] == []
        assert result["summary"]["n_papers"] == 0
        # Report opens with the canonical title regardless of paper count.
        assert "NCPR-Bench v1" in out_md.read_text()


# ── run_benchmark ────────────────────────────────────────────────────────────


class TestRunBenchmark:
    def test_two_papers_with_stubbed_synth(self, tmp_path):
        """Mocked holdout (2 papers) + injected synth -> aggregated result.

        Wires the orchestrator end-to-end through whatever sibling
        modules are currently importable (real or stub). Asserts the
        shape of the returned dict per spec §7 + the X5 aggregator
        contract.
        """
        holdout = tmp_path / "holdout.json"
        holdout.write_text(json.dumps({
            "papers": [
                {
                    "paper_id": "PR-001",
                    "paper_doi": "10.1/a",
                    "methods_text": "We used a binary classifier on EHR data.",
                },
                {
                    "paper_id": "PR-002",
                    "paper_doi": "10.1/b",
                    "methods_text": "Cross-sectional cohort, AUROC reported.",
                },
            ],
        }))

        # Minimal in-memory KB with concerns for both papers so the
        # match/score path has non-empty inputs.
        kb = tmp_path / "kb.json"
        kb.write_text(json.dumps({
            "entries": [
                {
                    "paper_doi": "10.1/a",
                    "reviewer_concerns": [
                        {
                            "concern_id": "C1",
                            "category": "leakage",
                            "dimension": "leakage",
                            "severity": "CRITICAL",
                            "concern_text": "future information used as feature",
                            "mlgg_rules": ["MLGG-F02"],
                            "mlgg_gates": ["leakage_gate"],
                        },
                        {
                            "concern_id": "C2",
                            "category": "evaluation",
                            "dimension": "evaluation",
                            "severity": "HIGH",
                            "concern_text": "no calibration reported",
                            "mlgg_rules": [],
                            "mlgg_gates": ["clinical_metrics_gate"],
                        },
                    ],
                },
                {
                    "paper_doi": "10.1/b",
                    "reviewer_concerns": [
                        {
                            "concern_id": "C3",
                            "category": "design",
                            "dimension": "design",
                            "severity": "MEDIUM",
                            "concern_text": "cohort definition ambiguous",
                            "mlgg_rules": [],
                            "mlgg_gates": ["cohort_definition_gate"],
                        },
                    ],
                },
            ],
        }))

        # Deterministic SUT — emits a flag whose code exact-matches the
        # first concern of paper a (leakage_gate).
        def fake_synth(paper, top_k=20, rag_only=True):
            if paper["paper_doi"] == "10.1/a":
                return [{
                    "code": "leakage_gate",
                    "severity": "CRITICAL",
                    "category": "leakage",
                    "evidence_text": "uses information from the prediction window",
                }]
            return []

        result = orch.run_benchmark(
            holdout_path=holdout,
            max_papers=None,
            rag_only=True,
            top_k=10,
            kb_path=kb,
            synth_fn=fake_synth,
        )

        # Top-level shape.
        assert result["schema_version"] == "ncpr-bench-v1"
        assert result["n_papers_evaluated"] == 2
        assert len(result["per_paper"]) == 2
        assert result["summary"]["n_papers"] == 2

        # Per-paper records expose the flat schema X5 consumes plus the
        # original nested score/coverage for diagnostics.
        for pp in result["per_paper"]:
            assert set(pp.keys()) >= {
                "paper_id", "n_flags", "n_concerns",
                "weighted_f1", "weighted_precision", "weighted_recall",
                "category_coverage", "paper_excluded",
                "_score", "_coverage",
            }
            for k in ("weighted_f1", "weighted_precision",
                      "weighted_recall", "category_coverage"):
                assert isinstance(pp[k], float)
                assert 0.0 <= pp[k] <= 1.0

        # Paper A had concerns loaded from the KB.
        pa = next(p for p in result["per_paper"] if p["paper_id"] == "PR-001")
        assert pa["n_concerns"] == 2
        assert pa["n_flags"] == 1
        assert pa["paper_excluded"] is False

        # Macro summary keys per the X5 (real or stub) contract.
        s = result["summary"]
        for k in ("macro_weighted_f1", "macro_weighted_precision",
                  "macro_weighted_recall", "macro_category_coverage"):
            assert k in s
            assert isinstance(s[k], (int, float))

    def test_max_papers_caps_evaluation(self, tmp_path):
        """--max-papers truncates the holdout list, not the KB."""
        holdout = tmp_path / "holdout.json"
        holdout.write_text(json.dumps([
            {"paper_id": f"P{i}", "paper_doi": f"10.1/{i}",
             "methods_text": f"paper {i}"}
            for i in range(5)
        ]))
        kb = tmp_path / "kb.json"
        kb.write_text(json.dumps({"entries": []}))

        result = orch.run_benchmark(
            holdout_path=holdout,
            max_papers=2,
            kb_path=kb,
            synth_fn=lambda paper, top_k=20, rag_only=True: [],
        )
        assert result["n_papers_evaluated"] == 2

    def test_unrecognized_holdout_shape_raises(self, tmp_path):
        """Defensive: unknown top-level shape fails loud, not silent."""
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"unexpected_key": []}))
        with pytest.raises(ValueError, match="unrecognized holdout shape"):
            orch.load_holdout(bad)


# ── Stub-fallback contract ───────────────────────────────────────────────────


class TestStubFallbacks:
    def test_stubbed_modules_list_is_tracked(self):
        """`_STUBBED` is a list. JSON output exposes it so CI can refuse
        to publish numbers when any stub is active."""
        assert isinstance(orch._STUBBED, list)

    def test_stub_match_all_shape(self):
        """The bound `_match_all` (real or stub) returns the documented
        keys so the per-paper loop never AttributeErrors."""
        out = orch._match_all([], [])
        for k in ("matched_pairs", "unmatched_flags", "unmatched_concerns"):
            assert k in out

    def test_aggregate_empty_input(self):
        """Aggregator returns zeroed scalars on empty input so the
        --max-papers 0 path produces a valid (if empty) summary."""
        out = orch._aggregate([])
        assert out["n_papers"] == 0
        # macro_weighted_f1 is the canonical X5 key (vs stub's older key).
        assert "macro_weighted_f1" in out

    def test_paper_query_text_extraction(self):
        """`_paper_query_text` prefers methods_text, then abstract,
        finally falls back to title fields so a stub-driven test that
        omits methods_text still produces a query string."""
        assert orch._paper_query_text({"methods_text": "abc"}) == "abc"
        assert orch._paper_query_text({"abstract": "xyz"}) == "xyz"
        assert orch._paper_query_text({"paper_id": "P1"}) == "P1"
