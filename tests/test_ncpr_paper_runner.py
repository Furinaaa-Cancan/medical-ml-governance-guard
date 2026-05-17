"""Unit tests for the NCPR per-paper MLGG runner (W22-X4).

All tests are offline and deterministic: ``rag_query`` and ``subprocess.run``
are mocked so we never need a live KB, network, or actual MLGG gates.
"""
from __future__ import annotations

import subprocess
from unittest import mock

from rag.evals import ncpr_paper_runner
from rag.evals.ncpr_paper_runner import (
    run_mlgg_pipeline,
    synthesize_flags_from_rag,
)


# ────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ────────────────────────────────────────────────────────────────────────


def _kb_record(cid: str, text: str, gate: str = "leakage_gate",
               severity: str = "HIGH",
               dimension: str = "design") -> dict:
    """Minimal KB record shape returned by ``rag_query`` in production."""
    return {
        "concern_id": cid,
        "concern_text": text,
        "severity": severity,
        "dimension": dimension,
        "code": gate,
        "_final_score": 0.9,
    }


# ────────────────────────────────────────────────────────────────────────
# synthesize_flags_from_rag — happy path + edge cases
# ────────────────────────────────────────────────────────────────────────


def test_synthesize_flags_from_rag_returns_one_flag_per_record():
    """rag_query returning 3 records -> exactly 3 MlggFlag, schema-compliant."""
    fake_records = [
        _kb_record("c1", "patient ids shared across train/test"),
        _kb_record("c2", "no calibration plot reported", gate="evaluation_quality_gate",
                   severity="MEDIUM", dimension="evaluation"),
        _kb_record("c3", "test set used for hyperparameter tuning"),
    ]
    with mock.patch(
        "scripts.rag.query.rag_query", return_value=fake_records
    ) as mocked:
        flags = synthesize_flags_from_rag("methods text here", top_k=3)

    assert mocked.called, "rag_query must be invoked"
    assert len(flags) == 3
    # MlggFlag schema: code, severity, category, evidence_text
    for f in flags:
        assert set(f.keys()) >= {"code", "severity", "category", "evidence_text"}
        assert isinstance(f["code"], str) and f["code"]
        assert isinstance(f["evidence_text"], str)
    assert flags[0]["evidence_text"] == "patient ids shared across train/test"
    assert flags[1]["severity"] == "MEDIUM"
    assert flags[1]["category"] == "evaluation"


def test_synthesize_flags_from_rag_empty_query_returns_empty_list():
    """Whitespace/empty query short-circuits to [] without touching rag_query."""
    with mock.patch("scripts.rag.query.rag_query") as mocked:
        assert synthesize_flags_from_rag("") == []
        assert synthesize_flags_from_rag("   \n") == []
    mocked.assert_not_called()


def test_synthesize_flags_prefers_mlgg_gates_over_concern_id():
    """W23 finding #1 regression: when rag_query returns records WITHOUT
    a ``code`` field but WITH ``mlgg_gates``, flag.code MUST be the first
    gate name (so ncpr_matcher's exact_code/code_prefix tiers can fire).
    Before the fix, flag.code fell through to concern_id (e.g. "PR-019-C02")
    which made those two matcher tiers structurally dead.
    """
    real_rag_record = {
        # Note: no "code" key — this mirrors actual scripts.rag.query.rag_query
        # output, where each KB row carries concern_id + mlgg_gates list.
        "concern_id": "PR-019-C02",
        "mlgg_gates": ["clinical_metrics_gate", "calibration_dca_gate"],
        "concern_text": "AUC alone is insufficient; provide PPV / NPV.",
        "severity": "HIGH",
        "dimension": "evaluation",
    }
    with mock.patch(
        "scripts.rag.query.rag_query", return_value=[real_rag_record]
    ):
        flags = synthesize_flags_from_rag("evaluation methods", top_k=1)
    assert len(flags) == 1
    assert flags[0]["code"] == "clinical_metrics_gate", (
        f"Expected first gate name, got {flags[0]['code']!r} "
        "(W23 finding #1 regression — see ncpr_paper_runner.py:_concern_to_flag)"
    )


def test_synthesize_flags_falls_back_to_concern_id_when_no_gates():
    """If a KB record has NO mlgg_gates and NO code, last-resort fallback
    is concern_id (preserves traceability even though matcher will miss)."""
    bare_record = {
        "concern_id": "PR-001-C99",
        "concern_text": "an orphan concern with no gate mapping",
        # no "code", no "failure_code", no "mlgg_gates"
    }
    with mock.patch(
        "scripts.rag.query.rag_query", return_value=[bare_record]
    ):
        flags = synthesize_flags_from_rag("anything", top_k=1)
    assert flags[0]["code"] == "PR-001-C99"


# ────────────────────────────────────────────────────────────────────────
# run_mlgg_pipeline — RAG-only fallback (no code repo)
# ────────────────────────────────────────────────────────────────────────


def test_run_mlgg_pipeline_no_code_repo_falls_back_to_rag_only():
    """Without code_repo_path, runner uses RAG only — no subprocess calls."""
    fake_records = [
        _kb_record("c1", "leakage of label into features"),
        _kb_record("c2", "no external validation"),
    ]
    with mock.patch(
        "scripts.rag.query.rag_query", return_value=fake_records
    ), mock.patch.object(subprocess, "run") as mocked_sub:
        result = run_mlgg_pipeline({
            "paper_id": "P001",
            "methods_text": "We used random splits on a single hospital cohort.",
            "code_repo_path": None,
        })

    mocked_sub.assert_not_called()
    assert result["paper_id"] == "P001"
    assert result["errors"] == []
    assert len(result["flags"]) == 2
    assert isinstance(result["wall_time_s"], float)
    assert result["wall_time_s"] >= 0


def test_run_mlgg_pipeline_missing_code_repo_key_is_treated_as_none():
    """``code_repo_path`` key absent entirely — still RAG-only, no crash."""
    with mock.patch(
        "scripts.rag.query.rag_query", return_value=[]
    ), mock.patch.object(subprocess, "run") as mocked_sub:
        result = run_mlgg_pipeline({
            "paper_id": "P002",
            "methods_text": "Methods.",
        })  # type: ignore[arg-type]

    mocked_sub.assert_not_called()
    assert result["paper_id"] == "P002"
    assert result["flags"] == []
    assert result["errors"] == []


# ────────────────────────────────────────────────────────────────────────
# run_mlgg_pipeline — subprocess merge path
# ────────────────────────────────────────────────────────────────────────


def _make_completed(returncode: int, stdout: str = "", stderr: str = ""):
    """Build a CompletedProcess stand-in for subprocess.run mocks."""
    return subprocess.CompletedProcess(
        args=["mocked"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_run_mlgg_pipeline_merges_subprocess_flags_when_code_repo_provided():
    """Both lint + audit subprocesses run; their JSON-stdout flags merge in."""
    rag_records = [_kb_record("rag1", "rag-derived concern")]
    lint_stdout = '{"flags":[{"code":"R001","severity":"HIGH",' \
                  '"category":"lint","evidence_text":"x=eval(...)"}]}'
    audit_stdout = '[{"code":"A001","severity":"LOW",' \
                   '"category":"audit","evidence_text":"no readme"}]'

    def fake_subprocess_run(cmd, **kwargs):
        joined = " ".join(cmd)
        if " lint " in joined or joined.endswith(" lint"):
            return _make_completed(0, stdout=lint_stdout)
        return _make_completed(0, stdout=audit_stdout)

    with mock.patch(
        "scripts.rag.query.rag_query", return_value=rag_records
    ), mock.patch.object(subprocess, "run", side_effect=fake_subprocess_run):
        result = run_mlgg_pipeline({
            "paper_id": "P003",
            "methods_text": "Some methods text.",
            "code_repo_path": "/tmp/fake-repo",
        }, timeout_s=30)

    codes = sorted(f["code"] for f in result["flags"])
    # 1 rag flag (mapped from KB code=leakage_gate) + 1 lint + 1 audit
    assert codes == ["A001", "R001", "leakage_gate"]
    assert result["errors"] == []


# ────────────────────────────────────────────────────────────────────────
# Timeout handling
# ────────────────────────────────────────────────────────────────────────


def test_run_mlgg_pipeline_subprocess_timeout_is_captured_in_errors():
    """TimeoutExpired on a subprocess -> error string, RAG flags still kept."""
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 0))

    with mock.patch(
        "scripts.rag.query.rag_query",
        return_value=[_kb_record("c1", "kept despite subprocess crash")],
    ), mock.patch.object(subprocess, "run", side_effect=fake_run):
        result = run_mlgg_pipeline({
            "paper_id": "P004",
            "methods_text": "m",
            "code_repo_path": "/tmp/some-repo",
        }, timeout_s=5)

    # Both lint and audit should report timeouts.
    assert len(result["errors"]) == 2
    assert all("timeout" in e.lower() for e in result["errors"])
    # RAG-derived flag (KB code=leakage_gate) must still be present —
    # subprocess failure is non-fatal.
    assert any(f["code"] == "leakage_gate" for f in result["flags"])
    assert any(
        f["evidence_text"] == "kept despite subprocess crash"
        for f in result["flags"]
    )


# ────────────────────────────────────────────────────────────────────────
# Error path: subprocess crash
# ────────────────────────────────────────────────────────────────────────


def test_run_mlgg_pipeline_subprocess_crash_captured_in_errors_list():
    """Non-zero (and non-2) returncode is recorded as an error."""
    def fake_run(cmd, **kwargs):
        return _make_completed(
            returncode=137,
            stdout="",
            stderr="Killed: 9\nOOMKiller invoked",
        )

    with mock.patch(
        "scripts.rag.query.rag_query", return_value=[]
    ), mock.patch.object(subprocess, "run", side_effect=fake_run):
        result = run_mlgg_pipeline({
            "paper_id": "P005",
            "methods_text": "m",
            "code_repo_path": "/tmp/crashy-repo",
        }, timeout_s=10)

    assert len(result["errors"]) == 2  # one per (lint, audit)
    assert all("exit=137" in e for e in result["errors"])
    assert result["flags"] == []  # no rag hits, no parsed subprocess stdout


def test_run_mlgg_pipeline_subprocess_returncode_2_is_not_an_error():
    """Return code 2 = MLGG gate flagged failures; still emits parsed flags."""
    stdout = '[{"code":"G01","severity":"HIGH","category":"design",' \
             '"evidence_text":"label leakage"}]'

    def fake_run(cmd, **kwargs):
        return _make_completed(returncode=2, stdout=stdout, stderr="")

    with mock.patch(
        "scripts.rag.query.rag_query", return_value=[]
    ), mock.patch.object(subprocess, "run", side_effect=fake_run):
        result = run_mlgg_pipeline({
            "paper_id": "P006",
            "methods_text": "m",
            "code_repo_path": "/tmp/repo-with-failures",
        }, timeout_s=10)

    assert result["errors"] == []
    assert len(result["flags"]) == 2  # one G01 per subprocess (lint + audit)
    assert all(f["code"] == "G01" for f in result["flags"])


# ────────────────────────────────────────────────────────────────────────
# Subprocess stdout parsing
# ────────────────────────────────────────────────────────────────────────


def test_parse_subprocess_flags_handles_ndjson_fallback():
    """Direct probe: NDJSON one-flag-per-line is accepted when JSON-object fails."""
    ndjson = (
        '{"code":"X1","severity":"LOW","category":"a","evidence_text":"t1"}\n'
        'not-json garbage line\n'
        '{"code":"X2","severity":"MED","category":"b","evidence_text":"t2"}\n'
    )
    flags = ncpr_paper_runner._parse_subprocess_flags(ndjson)
    assert [f["code"] for f in flags] == ["X1", "X2"]


def test_parse_subprocess_flags_empty_returns_empty():
    assert ncpr_paper_runner._parse_subprocess_flags("") == []
    assert ncpr_paper_runner._parse_subprocess_flags("   \n") == []
