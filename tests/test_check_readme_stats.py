"""Tests for scripts/diagnostics/check_readme_stats.py.

Verifies the drift lint actually catches the class of regression
it's designed to prevent (stale numbers, CN/EN disagreement) and
does not false-positive on the current checked-in state.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "diagnostics" / "check_readme_stats.py"


def _run(cwd: Path = REPO_ROOT):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--verbose"],
        capture_output=True, text=True, timeout=15,
        cwd=str(cwd),
    )


class TestDriftLint:

    def test_current_state_is_clean(self):
        """Guardrail: after 2026-04-23 stat updates, the drift lint
        should find CN and EN in agreement with the live KB."""
        r = _run()
        assert r.returncode == 0, (
            "README drift lint failed on HEAD — "
            "someone introduced stat drift since the last sync.\n"
            + r.stdout + r.stderr
        )
        assert "OK" in r.stdout

    def test_regex_still_matches_known_patterns(self):
        """If the README prose is re-worded in a way that invalidates
        every regex, the lint silently becomes useless. Fail if any
        claim matched zero things."""
        r = _run()
        assert "matched nothing" not in (r.stdout + r.stderr), (
            "A README claim pattern in check_readme_stats.py matched "
            "zero times. Either the README was rephrased (update the "
            "regex) or the claim was removed entirely (remove the "
            "entry from _CLAIMS)."
        )


class TestDriftDetection:
    """Simulate the two regression classes this lint is designed for
    by invoking the check() function directly against mutated copies."""

    def test_detects_stat_mismatch_via_regex(self, tmp_path, monkeypatch):
        # Copy READMEs + KB into a tmp dir, then tamper CN to say
        # "106 papers" while KB says 119. The lint must catch this.
        cn_copy = tmp_path / "README.md"
        en_copy = tmp_path / "README_EN.md"
        refs = tmp_path / "references" / "case-studies"
        refs.mkdir(parents=True)
        kb_copy = refs / "peer-review-kb.json"

        import shutil
        shutil.copy(REPO_ROOT / "README.md", cn_copy)
        shutil.copy(REPO_ROOT / "README_EN.md", en_copy)
        shutil.copy(
            REPO_ROOT / "references" / "case-studies" / "peer-review-kb.json",
            kb_copy,
        )

        # Tamper: flip CN to say 106 papers.
        original = cn_copy.read_text(encoding="utf-8")
        tampered = original.replace(
            "119 篇 NC 审稿证据", "106 篇 NC 审稿证据", 1,
        )
        assert tampered != original, \
            "fixture setup broke — couldn't find the CN tagline to tamper"
        cn_copy.write_text(tampered, encoding="utf-8")

        # Patch the module's ROOT so it reads the tampered files.
        import importlib.util
        spec = importlib.util.spec_from_file_location("chkr", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        monkeypatch.setattr("sys.path",
                            [str(REPO_ROOT / "scripts" / "core")] + sys.path)
        spec.loader.exec_module(mod)
        monkeypatch.setattr(mod, "ROOT", tmp_path)
        monkeypatch.setattr(mod, "CN", cn_copy)
        monkeypatch.setattr(mod, "EN", en_copy)
        monkeypatch.setattr(mod, "KB", kb_copy)
        # Refresh the _CLAIMS doc bindings to tmp copies.
        for claim in mod._CLAIMS:
            if claim["doc"].name == "README.md":
                claim["doc"] = cn_copy
            else:
                claim["doc"] = en_copy

        exit_code, errors = mod.check()
        assert exit_code == 2
        # At least one error should reference the CN tagline mismatch.
        assert any("106" in e and "119" in e for e in errors), errors
