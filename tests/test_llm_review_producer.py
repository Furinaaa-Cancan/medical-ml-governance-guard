"""LLM review synthesis producer (P1.0a): evidence -> adapter -> review report.

Covers the producer plumbing with the deterministic test double (no network),
the guard that the live adapter never makes an unattended call, and the
producer->consumer integration: a blocking concern fails publication_gate, an
advisory concern only warns.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REVIEW = Path(__file__).resolve().parents[1] / "scripts" / "review"
if str(_REVIEW) not in sys.path:
    sys.path.insert(0, str(_REVIEW))

import pytest  # noqa: E402

from llm_review import (  # noqa: E402
    DeterministicReviewAdapter,
    LiveClaudeReviewAdapter,
    gather_evidence,
    run_llm_review,
)
from test_publication_gate import _build_cmd, _make_all_artifacts  # noqa: E402


def _write_report(path: Path, **fields):
    path.write_text(json.dumps(fields), encoding="utf-8")


def test_gather_evidence_reads_reports(tmp_path: Path):
    _write_report(tmp_path / "leakage_report.json", gate_name="leakage_gate", status="pass",
                  failure_count=0, warning_count=1, warnings=[{"code": "w1", "message": "m"}], run_id="R1")
    _write_report(tmp_path / "tuning_report.json", gate_name="tuning_gate", status="pass", run_id="R1")

    ctx = gather_evidence(tmp_path)
    assert ctx["gate_count"] == 2
    assert ctx["run_id"] == "R1"
    gates = {g["gate"]: g for g in ctx["gates"]}
    assert gates["leakage_gate"]["warnings"][0]["code"] == "w1"


def test_deterministic_adapter_echoes_warnings(tmp_path: Path):
    ctx = {"gates": [{"gate": "leakage_gate", "warnings": [{"code": "no_dca", "message": "add DCA"}]}],
           "gate_count": 1}
    out = DeterministicReviewAdapter().synthesize(ctx)
    assert out["concerns"][0]["severity"] == "advisory"
    assert out["concerns"][0]["code"] == "echo_no_dca"
    assert out["meta"]["model"] == "deterministic-double"
    assert len(out["meta"]["prompt_hash"]) == 64
    assert out["meta"]["evidence_seen"] == 1


def test_deterministic_adapter_explicit_concerns():
    given = [{"severity": "blocking", "code": "f02", "message": "post-index", "detail": {}}]
    out = DeterministicReviewAdapter(concerns=given).synthesize({"gates": [], "gate_count": 0})
    assert out["concerns"] == given


def test_run_llm_review_writes_p00_schema(tmp_path: Path):
    _write_report(tmp_path / "leakage_report.json", gate_name="leakage_gate", status="pass", run_id="RUN-9")
    report = run_llm_review(tmp_path)

    written = json.loads((tmp_path / "llm_review_report.json").read_text())
    assert written == report
    assert "concerns" in written and isinstance(written["concerns"], list)
    assert "meta" in written
    assert written["run_id"] == "RUN-9"


def test_live_adapter_never_calls_when_disabled():
    with pytest.raises(RuntimeError):
        LiveClaudeReviewAdapter().synthesize({"gates": []})
    # enabled but no client → still guarded
    with pytest.raises(RuntimeError):
        LiveClaudeReviewAdapter(enabled=True).synthesize({"gates": []})


# ── producer -> consumer integration ─────────────────────────────────────────

def _run_pub_gate(tmp_path, paths):
    result = subprocess.run(_build_cmd(tmp_path, paths), capture_output=True, text=True, timeout=30)
    report = json.loads((tmp_path / "report.json").read_text())
    return result, report


def test_producer_blocking_concern_fails_publication(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    run_llm_review(tmp_path, adapter=DeterministicReviewAdapter(concerns=[
        {"severity": "blocking", "code": "f02_post_index", "message": "post-index feature", "detail": {}},
    ]))
    result, report = _run_pub_gate(tmp_path, paths)
    assert result.returncode == 2
    assert "llm_blocking_concern" in [f.get("code") for f in report.get("failures", [])]


def test_producer_advisory_concern_only_warns(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    run_llm_review(tmp_path, adapter=DeterministicReviewAdapter(concerns=[
        {"severity": "advisory", "code": "minor", "message": "consider NRI", "detail": {}},
    ]))
    result, report = _run_pub_gate(tmp_path, paths)
    assert result.returncode == 0
    assert "llm_advisory_concern" in [w.get("code") for w in report.get("warnings", [])]
