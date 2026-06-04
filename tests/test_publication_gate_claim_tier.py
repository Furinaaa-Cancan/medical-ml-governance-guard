"""Honest claim-tier naming in publication_gate.summary.claim (P2.0).

The claim tier is bound to the deterministic floor, not the LLM layer:
  - publication-grade = full gates + verified attestation (L3),
  - leakage-audited   = deterministic leakage gates pass (L1/L2), not yet L3,
  - none              = floor not met, incl. a blocking reviewer concern.
The LLM advisory layer is reported separately and can only LOWER the tier.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from test_publication_gate import _build_cmd, _make_all_artifacts, _write_json


def _run(tmp_path, paths):
    result = subprocess.run(_build_cmd(tmp_path, paths), capture_output=True, text=True, timeout=30)
    return result, json.loads((tmp_path / "report.json").read_text())


def test_all_pass_is_publication_grade(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    _, report = _run(tmp_path, paths)
    claim = report["summary"]["claim"]
    assert claim["tier"] == "publication-grade"
    assert claim["reviewer_concerns_incorporated"] is False


def test_l3_only_failure_is_leakage_audited(tmp_path: Path):
    # fairness_equity is an L3-only gate: failing it drops L3 but keeps L1/L2.
    paths = _make_all_artifacts(tmp_path)
    _write_json(paths["fairness_equity_report"], {"status": "fail", "strict_mode": True, "failure_count": 1})
    _, report = _run(tmp_path, paths)
    assert report["summary"]["claim"]["tier"] == "leakage-audited"


def test_blocking_reviewer_concern_caps_to_none(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    (tmp_path / "llm_review_report.json").write_text(
        json.dumps({"concerns": [
            {"severity": "blocking", "code": "f02", "message": "post-index feature", "detail": {}},
        ]}),
        encoding="utf-8",
    )
    _, report = _run(tmp_path, paths)
    claim = report["summary"]["claim"]
    assert claim["tier"] == "none"
    assert claim["reviewer_concerns_incorporated"] is True
    assert claim["blocking_reviewer_concerns"] == 1


def test_advisory_concern_keeps_tier_but_records_it(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    (tmp_path / "llm_review_report.json").write_text(
        json.dumps({"concerns": [
            {"severity": "advisory", "code": "minor", "message": "consider NRI", "detail": {}},
        ]}),
        encoding="utf-8",
    )
    _, report = _run(tmp_path, paths)
    claim = report["summary"]["claim"]
    # advisory does not lower the deterministic tier (non-strict run)
    assert claim["tier"] == "publication-grade"
    assert claim["advisory_reviewer_concerns"] == 1
