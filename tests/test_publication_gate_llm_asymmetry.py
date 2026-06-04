"""Asymmetric two-tier harness invariant for publication_gate.

The LLM advisory channel may ONLY raise concerns. It can never clear a
deterministic gate failure (final_verdict = min(gate, llm)). These tests pin
that invariant at the certification boundary:

  * a deterministic gate FAIL cannot be upgraded to pass by any LLM report;
  * a blocking LLM concern CAN fail an otherwise-passing run and cap the tier;
  * an advisory LLM concern warns (and fails only under --strict);
  * an absent report is a no-op (LLM review is optional);
  * a present-but-malformed report is fail-closed.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

# Reuse the established fixture harness from the main gate test module.
from test_publication_gate import (  # noqa: E402
    _build_cmd,
    _make_all_artifacts,
    _write_json,
)


def _run(tmp_path, paths, extra_args=None):
    cmd = _build_cmd(tmp_path, paths, extra_args=extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    report = json.loads((tmp_path / "report.json").read_text())
    return result, report


def _write_llm(tmp_path: Path, payload) -> Path:
    """Write the conventionally-discovered advisory artifact next to --report."""
    path = tmp_path / "llm_review_report.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")  # raw (possibly malformed)
    else:
        _write_json(path, payload)
    return path


# ── invariant 1: no upgrade ────────────────────────────────────────────────

def test_llm_cannot_upgrade_a_gate_failure(tmp_path: Path):
    """A real gate FAIL stays a fail no matter what the LLM report claims."""
    paths = _make_all_artifacts(tmp_path)
    # deterministic failure: leakage gate failed
    _write_json(paths["leakage_report"], {"status": "fail", "strict_mode": True, "failure_count": 1})
    # an LLM report that tries every trick to flip the verdict
    _write_llm(tmp_path, {"status": "pass", "override": True, "compliance_level": "L3", "concerns": []})

    result, report = _run(tmp_path, paths)

    assert result.returncode == 2, "gate failure must not be rescued by the LLM report"
    assert report["status"] == "fail"
    tiers = report["summary"]["compliance_tiers"]
    assert tiers["L1_leakage_audit"] is False
    assert tiers["L3_publication_grade"] is False


# ── invariant 2: can block ──────────────────────────────────────────────────

def test_llm_blocking_concern_fails_a_passing_run(tmp_path: Path):
    """A passing run is failed (and tier capped to none) by a blocking concern."""
    paths = _make_all_artifacts(tmp_path)
    _write_llm(tmp_path, {"concerns": [
        {"severity": "blocking", "code": "f02_post_index_feature",
         "message": "lab_value_3 is measured after the prediction index.",
         "detail": {"feature": "lab_value_3"}},
    ]})

    result, report = _run(tmp_path, paths)

    assert result.returncode == 2
    assert report["status"] == "fail"
    assert report["summary"]["compliance_level"] == "none"
    assert report["summary"]["llm_advisory_review"]["blocking_count"] == 1
    codes = [f.get("code") for f in report.get("failures", [])]
    assert "llm_blocking_concern" in codes


# ── invariant 3: advisory warns, fails only under --strict ───────────────────

def test_llm_advisory_concern_warns_without_strict(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    _write_llm(tmp_path, {"concerns": [
        {"severity": "advisory", "code": "minor_concern", "message": "Consider reporting NRI."},
    ]})

    result, report = _run(tmp_path, paths)

    assert result.returncode == 0, "an advisory concern must not fail a non-strict run"
    assert report["status"] == "pass"
    assert report["summary"]["llm_advisory_review"]["advisory_count"] == 1
    codes = [w.get("code") for w in report.get("warnings", [])]
    assert "llm_advisory_concern" in codes


def test_llm_advisory_concern_fails_under_strict(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    _write_llm(tmp_path, {"concerns": [
        {"severity": "advisory", "code": "minor_concern", "message": "Consider reporting NRI."},
    ]})

    result, report = _run(tmp_path, paths, extra_args=["--strict"])

    assert result.returncode == 2
    assert report["status"] == "fail"


# ── invariant 4: absent is a no-op ───────────────────────────────────────────

def test_absent_llm_report_is_noop(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    # no llm_review_report.json written
    result, report = _run(tmp_path, paths)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["summary"]["llm_advisory_review"]["present"] is False


# ── invariant 5: malformed is fail-closed ────────────────────────────────────

def test_unparseable_llm_report_is_fail_closed(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    _write_llm(tmp_path, "{ this is not json")

    result, report = _run(tmp_path, paths)

    assert result.returncode == 2
    codes = [f.get("code") for f in report.get("failures", [])]
    assert "llm_review_unparseable" in codes


def test_non_object_llm_report_is_fail_closed(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    _write_llm(tmp_path, ["not", "an", "object"])

    result, report = _run(tmp_path, paths)

    assert result.returncode == 2
    codes = [f.get("code") for f in report.get("failures", [])]
    assert "llm_review_malformed" in codes


def test_concern_with_non_list_is_fail_closed(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    _write_llm(tmp_path, {"concerns": "should-be-a-list"})

    result, report = _run(tmp_path, paths)

    assert result.returncode == 2
    codes = [f.get("code") for f in report.get("failures", [])]
    assert "llm_review_malformed" in codes


# ── P1.1: advisory audit trail (content hash + provenance) ───────────────────

def test_advisory_report_content_is_hashed(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    llm_path = _write_llm(tmp_path, {"concerns": [
        {"severity": "advisory", "code": "minor", "message": "consider X"},
    ]})

    _, report = _run(tmp_path, paths)

    rb = report["summary"]["llm_advisory_review"]
    assert rb["content_sha256"] == hashlib.sha256(llm_path.read_bytes()).hexdigest()
    assert len(rb["content_sha256"]) == 64


def test_advisory_report_provenance_surfaced(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    meta = {"model": "claude-opus-4-8", "prompt_hash": "deadbeef", "evidence_seen": 28}
    _write_llm(tmp_path, {"meta": meta, "concerns": []})

    _, report = _run(tmp_path, paths)

    assert report["summary"]["llm_advisory_review"]["provenance"] == meta


def test_absent_report_has_no_hash_or_provenance(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    _, report = _run(tmp_path, paths)

    rb = report["summary"]["llm_advisory_review"]
    assert rb["content_sha256"] is None
    assert rb["provenance"] == {}


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", str(Path(__file__))]))
