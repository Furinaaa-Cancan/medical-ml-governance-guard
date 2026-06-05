"""The manifest artifact is sealed by its producer (manifest_lock) under a run key.

publication_gate seal-verifies the manifest like a gate report, but manifest_lock
writes the manifest ARTIFACT via raw write_json (not build_report_envelope). This
is the PRODUCER-LEVEL regression test for the "unsealed manifest fails every
orchestrated publication run" blocker — it would have caught it, unlike the
fixtures that hand-seal the manifest.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
KEY = "c" * 64


def _run_manifest_lock(inp: Path, out: Path, key=KEY):
    env = dict(os.environ)
    if key is None:
        env.pop("MLGG_RUN_KEY", None)
    else:
        env["MLGG_RUN_KEY"] = key
    cmd = [sys.executable, str(SCRIPTS_DIR / "gates/manifest_lock.py"),
           "--inputs", str(inp), "--output", str(out)]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)


def test_manifest_is_sealed_and_verifies_under_run_key(tmp_path: Path):
    from _security import verify_envelope_seal

    f = tmp_path / "data.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    out = tmp_path / "manifest.json"
    _run_manifest_lock(f, out)

    manifest = json.loads(out.read_text())
    assert "seal" in manifest, "real manifest_lock must seal its output under a run key"
    assert verify_envelope_seal(manifest, KEY) is True


def test_manifest_unsealed_without_key(tmp_path: Path):
    f = tmp_path / "data.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    out = tmp_path / "manifest.json"
    _run_manifest_lock(f, out, key=None)

    manifest = json.loads(out.read_text())
    assert "seal" not in manifest  # backward-compatible: no key -> no seal
