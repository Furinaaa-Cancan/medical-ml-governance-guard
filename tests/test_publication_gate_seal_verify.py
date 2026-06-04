"""publication_gate verifies run-scoped seals before trusting status (P0.3b consumer).

This is the C2 fix: an agent that hand-edits a gate report (e.g. flips a failed
leakage gate's status to "pass") cannot re-seal it without the per-run key, so
the certifier detects the tamper and fails closed — even though status="pass".
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from _security import compute_envelope_seal
from test_publication_gate import _build_cmd, _make_all_artifacts

KEY = "b" * 64


def _seal_file(path: Path, key: str = KEY) -> None:
    r = json.loads(path.read_text(encoding="utf-8"))
    r["seal"] = compute_envelope_seal(r, key)
    path.write_text(json.dumps(r, indent=2), encoding="utf-8")


def _seal_all(paths, key: str = KEY) -> None:
    for p in paths.values():
        _seal_file(p, key)


def _run(tmp_path, paths, key=KEY, extra_args=None):
    cmd = _build_cmd(tmp_path, paths, extra_args=extra_args)
    env = dict(os.environ)
    if key is None:
        env.pop("MLGG_RUN_KEY", None)
    else:
        env["MLGG_RUN_KEY"] = key
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    report = json.loads((tmp_path / "report.json").read_text())
    return result, report


def test_sealed_reports_pass(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    _seal_all(paths)
    result, report = _run(tmp_path, paths)

    assert result.returncode == 0
    sv = report["summary"]["seal_verification"]
    assert sv["active"] is True
    assert sv["invalid"] == []
    assert sv["verified"] >= 1


def test_tampered_status_caught_by_seal(tmp_path: Path):
    # C2 attack: leakage gate FAILED; agent flips status->pass without re-sealing.
    paths = _make_all_artifacts(tmp_path)
    _seal_all(paths)
    r = {"status": "fail", "strict_mode": True, "failure_count": 1}
    r["seal"] = compute_envelope_seal(r, KEY)   # seal binds status=fail
    r["status"] = "pass"                          # tamper, keep stale seal
    r["failure_count"] = 0
    paths["leakage_report"].write_text(json.dumps(r, indent=2), encoding="utf-8")

    result, report = _run(tmp_path, paths)

    assert result.returncode == 2
    codes = [f.get("code") for f in report.get("failures", [])]
    assert "component_seal_invalid" in codes
    assert "leakage_report" in report["summary"]["seal_verification"]["invalid"]


def test_no_key_is_noop(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)  # unsealed
    result, report = _run(tmp_path, paths, key=None)

    assert result.returncode == 0
    assert report["summary"]["seal_verification"]["active"] is False


def test_unsealed_warns_without_strict_but_fails_under_strict(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)  # key active but reports unsealed
    result, report = _run(tmp_path, paths)

    assert result.returncode == 0  # warnings don't fail a non-strict run
    sv = report["summary"]["seal_verification"]
    assert sv["active"] is True
    assert len(sv["unsealed"]) >= 1

    result_strict, _ = _run(tmp_path, paths, extra_args=["--strict"])
    assert result_strict.returncode == 2
