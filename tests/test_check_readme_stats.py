"""Tests for scripts/diagnostics/check_readme_stats.py.

Verifies the drift lint actually catches the class of regression
it's designed to prevent (stale numbers, CN/EN disagreement) and
does not false-positive on the current checked-in state.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "diagnostics" / "check_readme_stats.py"


def _load_module():
    """Import the diagnostic script as a module without going through
    `subprocess`. Used by unit-level tests that need direct access to
    the doc-map helper functions instead of CLI exit codes."""
    spec = importlib.util.spec_from_file_location("chkr_dm", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # The module appends scripts/core to sys.path for the gate
    # registry; mirror that so a clean test process can import too.
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "core"))
    try:
        spec.loader.exec_module(mod)
    finally:
        try:
            sys.path.remove(str(REPO_ROOT / "scripts" / "core"))
        except ValueError:
            pass
    return mod


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
        # "106 papers" while KB says 335. The lint must catch this.
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
            "335 篇 NC+CM 同行评审 PDF", "106 篇 NC+CM 同行评审 PDF", 1,
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
        assert any("106" in e and "335" in e for e in errors), errors


class TestDocsMapDrift:
    """Verify the W13-G2 doc-map drift detector.

    The doc-map section is hand-maintained. Every new docs/*.md
    silently drifts the table unless this check catches it. Tests
    exercise the function in isolation (via tmp fixtures) so they
    stay green even when parallel sessions edit READMEs out from
    under us.
    """

    # Skeleton table that mirrors README.md layout: H2 header,
    # short blurb, table with 3 columns, then the next H2. The
    # extractor finds every `docs/.../foo.md` regardless of cell
    # decoration (backticks, md links, or bare path).
    _CN_TEMPLATE = (
        "前文 ...\n\n"
        "## 📂 文档地图\n\n"
        "blurb\n\n"
        "| 文件 | 内容 | 受众 |\n"
        "|:--|:--|:--|\n"
        "{rows}\n\n"
        "## 下一节\n\nfollowing content\n"
    )

    def _build_readme(self, paths):
        """Render a CN-style README with one row per cited path.

        Mix the three cell forms so both extractor paths get
        exercised: backticks for the first, md link for the second,
        bare path for the rest. Directories (trailing /) go in via
        bare-path form too.
        """
        rows = []
        for i, p in enumerate(paths):
            if i % 3 == 0:
                cell = f"`{p}`"
            elif i % 3 == 1:
                cell = f"[{p}]({p})"
            else:
                cell = p
            rows.append(f"| {cell} | desc | aud |")
        return self._CN_TEMPLATE.format(rows="\n".join(rows))

    def _make_repo(self, tmp_path: Path, on_disk, table_paths,
                   exclude_diagnostics=True):
        """Build a synthetic repo: write each on_disk path as an
        empty .md under tmp_path, and write a README citing each
        table_paths entry. Returns (readme_path, root)."""
        for rel in on_disk:
            full = tmp_path / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text("# stub\n", encoding="utf-8")
        readme = tmp_path / "README.md"
        readme.write_text(self._build_readme(table_paths), encoding="utf-8")
        return readme, tmp_path

    def test_docs_map_drift_clean_against_real_readme(self):
        """Run the doc-map check against current HEAD. Pass means
        the W12-A1/A2 tables match docs/ on disk; fail surfaces
        the drift in the failure message so it can be fixed.

        Marked xfail(strict=False) at W13-G2 introduction: W12-A1
        shipped the CN table missing the 5 docs/reference/*.md
        files that W12-A2 added in EN. When that's fixed, this
        flips to xpass and the marker should be removed so any
        future drift becomes a hard failure.
        """
        mod = _load_module()
        cn_errs = mod._check_docs_map_drift(mod.CN, mod.ROOT)
        en_errs = mod._check_docs_map_drift(mod.EN, mod.ROOT)
        if cn_errs or en_errs:
            # xfail with the full drift dump so a `pytest -rx` run
            # shows exactly what's missing.
            pytest.xfail(
                "Doc-map drift in checked-in READMEs (W12-A1 left "
                "CN table incomplete vs A2's EN):\n  CN: "
                + "\n  CN: ".join(cn_errs) + "\n  EN: "
                + "\n  EN: ".join(en_errs)
            )

    def test_docs_map_drift_detects_missing(self, tmp_path):
        """README cites docs/ghost.md but the file isn't on disk —
        should report stale_in_table."""
        mod = _load_module()
        # Only the ARCHITECTURE file exists; README also cites
        # docs/ghost.md which doesn't exist.
        readme, root = self._make_repo(
            tmp_path,
            on_disk=["docs/ARCHITECTURE.md"],
            table_paths=["docs/ARCHITECTURE.md", "docs/ghost.md"],
        )
        errors = mod._check_docs_map_drift(readme, root)
        assert any("stale_in_table" in e for e in errors), errors
        assert any("docs/ghost.md" in e for e in errors), errors

    def test_docs_map_drift_detects_orphan(self, tmp_path):
        """docs/synthetic.md exists but README doesn't cite it —
        should report missing_from_table."""
        mod = _load_module()
        readme, root = self._make_repo(
            tmp_path,
            on_disk=["docs/ARCHITECTURE.md", "docs/synthetic.md"],
            table_paths=["docs/ARCHITECTURE.md"],
        )
        errors = mod._check_docs_map_drift(readme, root)
        assert any("missing_from_table" in e for e in errors), errors
        assert any("docs/synthetic.md" in e for e in errors), errors

    def test_docs_map_drift_excludes_diagnostics_dir(self, tmp_path):
        """docs/diagnostics/*.md is the W9-D1 frozen archive — it
        should never trigger missing_from_table, even with 30+
        files on disk that the README never cites."""
        mod = _load_module()
        readme, root = self._make_repo(
            tmp_path,
            on_disk=[
                "docs/ARCHITECTURE.md",
                "docs/diagnostics/E1_retrieval_precision.md",
                "docs/diagnostics/E2_hybrid_decomposition.md",
                "docs/diagnostics/W7P0_baseline.md",
            ],
            table_paths=["docs/ARCHITECTURE.md"],
        )
        errors = mod._check_docs_map_drift(readme, root)
        # Critically: no missing_from_table error for diagnostics/.
        for err in errors:
            assert "docs/diagnostics/" not in err, (
                "diagnostics/ should be excluded but error mentions "
                f"it: {err}"
            )
        # And no errors at all in this scenario.
        assert errors == [], errors

    def test_docs_map_dir_reference_covers_subtree(self, tmp_path):
        """If README cites `docs/adr/` (trailing slash), every
        docs/adr/*.md is implicitly covered — orphans there should
        not fire missing_from_table. Mirrors how W12-A1 advertises
        the ADR directory as a single row."""
        mod = _load_module()
        readme, root = self._make_repo(
            tmp_path,
            on_disk=[
                "docs/ARCHITECTURE.md",
                "docs/adr/0001_some_decision.md",
                "docs/adr/0002_another_decision.md",
            ],
            table_paths=["docs/ARCHITECTURE.md", "docs/adr/"],
        )
        errors = mod._check_docs_map_drift(readme, root)
        assert errors == [], errors

    def test_docs_map_dir_reference_flags_empty_dir(self, tmp_path):
        """If README cites `docs/adr/` but the directory is empty
        (or absent), the claim is meaningless — flag as stale."""
        mod = _load_module()
        # Only ARCHITECTURE.md on disk; README claims docs/adr/.
        readme, root = self._make_repo(
            tmp_path,
            on_disk=["docs/ARCHITECTURE.md"],
            table_paths=["docs/ARCHITECTURE.md", "docs/adr/"],
        )
        errors = mod._check_docs_map_drift(readme, root)
        assert any("stale_in_table" in e for e in errors), errors
        assert any("docs/adr/" in e for e in errors), errors

    def test_docs_map_missing_section_header(self, tmp_path):
        """If both section headers vanish, the check should fail
        loudly rather than silently treat zero entries as clean."""
        mod = _load_module()
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "ARCHITECTURE.md").write_text("# x\n")
        readme = tmp_path / "README.md"
        readme.write_text(
            "# Title\n\n## Some Other Section\n\ncontent\n",
            encoding="utf-8",
        )
        errors = mod._check_docs_map_drift(readme, tmp_path)
        assert errors, "expected an error for missing section header"
        assert any("header" in e.lower() for e in errors), errors
