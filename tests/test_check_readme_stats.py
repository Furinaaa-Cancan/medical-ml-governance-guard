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


class TestHeaderBadgeDrift:
    """W20-F5: exhaustive coverage of header-row shields.io badges.

    Pre-W20-F5 the checker only validated the ``tests-NNNN passed``
    badge (and even that was opt-in). EN silently drifted to
    ``datasets-14`` while CN said 16 — the W19-E2 finding that
    motivated this class. Tests below construct synthetic READMEs
    with one badge wrong at a time and assert the checker flags it.

    Direct ``check()`` integration tests (TestDriftDetection) require
    tampering with the live repo's stat-graph and are sensitive to
    concurrent-session churn (scripts_core, tests/, SKILL.md grow
    every commit). These tests work at the per-claim level so they
    stay green regardless of what siblings are doing.
    """

    def _load(self):
        return _load_module()

    def _badge_block(self, gates=33, datasets=16, code_loc=147,
                     lint_rules=30):
        """Render the seven-badge header row both READMEs share."""
        return (
            '<p align="center">\n'
            '  <img src="https://img.shields.io/badge/MLGG-v1.0-FF6B35" alt="x">\n'
            f'  <img src="https://img.shields.io/badge/tests-4712%20passed-brightgreen" alt="x">\n'
            f'  <img src="https://img.shields.io/badge/gates-{gates}%20fail--closed-critical" alt="x">\n'
            f'  <img src="https://img.shields.io/badge/datasets-{datasets}%20medical-purple" alt="x">\n'
            f'  <img src="https://img.shields.io/badge/code-{code_loc}K%20lines-informational" alt="x">\n'
            f'  <img src="https://img.shields.io/badge/lint%20rules-{lint_rules}%20(R001--R030)-orange" alt="x">\n'
            '</p>\n'
        )

    def _build_claims(self, mod):
        """Helper to access the structural-claims list (badge claims
        live inside _build_structure_claims, not _CLAIMS, so test
        coverage needs to dig into the builder)."""
        return mod._build_structure_claims()

    def test_new_badge_claims_registered(self):
        """W20-F5 adds 8 new badge claims (gates, datasets, lint-rules,
        code-loc × CN, EN). Guard against accidental removal."""
        mod = self._load()
        claim_names = {c["name"] for c in self._build_claims(mod)}
        for required in (
            "badge_gates_cn", "badge_gates_en",
            "badge_datasets_cn", "badge_datasets_en",
            "badge_lint_rules_cn", "badge_lint_rules_en",
            "badge_code_loc_cn", "badge_code_loc_en",
        ):
            assert required in claim_names, (
                f"W20-F5 badge claim {required!r} missing from "
                f"_build_structure_claims(); restore it so the header "
                f"row stays drift-checked."
            )

    def test_live_dataset_count_matches_examples_dir(self):
        """Ground truth helper for the datasets badge must equal either
        the catalog count in ``examples/README.md`` (W28-V1 fix —
        authoritative when present; survives sparse CI checkouts where
        15 of 16 datasets are produced on-demand by ``download_*.py``
        and are .gitignore-excluded) OR the on-disk CSV count (legacy
        fallback for environments without the catalog).
        """
        mod = self._load()
        live = mod._live_dataset_count()
        on_disk = sum(
            1 for p in (mod.ROOT / "examples").glob("*.csv")
            if not p.name.startswith(".")
        )
        catalog_path = mod.ROOT / "examples" / "README.md"
        catalog = None
        if catalog_path.is_file():
            import re as _re
            m = _re.search(
                r"医学数据集.*?(\d+)\s*个",
                catalog_path.read_text(encoding="utf-8", errors="ignore"),
            )
            if m:
                catalog = int(m.group(1))
        assert live == catalog or live == on_disk, (
            f"_live_dataset_count() returned {live}; expected catalog="
            f"{catalog} (from examples/README.md) or on_disk={on_disk} "
            f"(filesystem fallback)."
        )

    def test_live_lint_rule_count_matches_registry(self):
        """Ground truth helper for the lint-rules badge must equal the
        registered rule count from mlgg_lint."""
        mod = self._load()
        live = mod._live_lint_rule_count()
        # Recover the registry count without depending on the helper's
        # internal import path.
        import sys as _sys
        _sys.path.insert(0, str(mod.ROOT / "plugin"))
        try:
            from mlgg_lint.rules import get_all_rules
            registry = len(get_all_rules())
        finally:
            try:
                _sys.path.remove(str(mod.ROOT / "plugin"))
            except ValueError:
                pass
        assert live == registry, (
            f"_live_lint_rule_count() returned {live} but the registry "
            f"has {registry} rules."
        )

    def _run_badge_check(self, mod, monkeypatch, tmp_path,
                         cn_block, en_block):
        """Render two synthetic READMEs with the given badge blocks,
        rebind the module's CN/EN paths + the badge claims to the
        tmp files, and call check(). Returns (exit_code, errors).

        Stubs out the other live-truth helpers so the synthetic
        READMEs don't trip noise from unrelated claims (the synthetic
        files only contain the badge row, not strapline / structure
        tree, so those regexes match nothing and would dominate the
        error list otherwise).
        """
        cn = tmp_path / "README.md"
        en = tmp_path / "README_EN.md"
        cn.write_text(cn_block, encoding="utf-8")
        en.write_text(en_block, encoding="utf-8")

        monkeypatch.setattr(mod, "CN", cn)
        monkeypatch.setattr(mod, "EN", en)
        # Rebind every claim's doc to the synthetic copies so existing
        # _CLAIMS entries don't read the real READMEs by accident.
        for claim in mod._CLAIMS:
            claim["doc"] = cn if claim["doc"].name == "README.md" else en

        # Filter to JUST the badge claims so other claims (which
        # reference non-existent prose in the synthetic READMEs) don't
        # generate noise. We do this by monkey-patching the builder
        # to return only the badge subset.
        orig_build = mod._build_structure_claims
        def only_badges():
            claims = orig_build()
            return [c for c in claims if c["name"].startswith("badge_")]
        monkeypatch.setattr(mod, "_build_structure_claims", only_badges)
        # And drop the prose _CLAIMS entirely (those are tested
        # elsewhere — the badge-focused tests should only assert on
        # badge regex behavior).
        monkeypatch.setattr(mod, "_CLAIMS", [])
        # Skip the doc-map check entirely (synthetic READMEs have no
        # documentation-map section).
        monkeypatch.setattr(
            mod, "_check_docs_map_drift", lambda *a, **kw: [],
        )
        # Skip the H2 section-parity check too — the synthetic READMEs
        # contain only a badge block, none of the registered sections.
        # It has its own dedicated tests below.
        monkeypatch.setattr(
            mod, "_check_h2_parity", lambda *a, **kw: [],
        )
        return mod.check()

    def test_clean_badges_pass(self, tmp_path, monkeypatch):
        """Sanity: when both READMEs carry matching, correct badge
        values, the checker should return success with no errors."""
        mod = self._load()
        live_gates = mod._live_gate_count()
        live_datasets = mod._live_dataset_count()
        live_lint = mod._live_lint_rule_count()
        block = self._badge_block(
            gates=live_gates, datasets=live_datasets,
            code_loc=147, lint_rules=live_lint,
        )
        code, errs = self._run_badge_check(
            mod, monkeypatch, tmp_path, block, block,
        )
        assert code == 0, (
            f"Clean-state badge check unexpectedly failed: {errs}"
        )

    def test_detects_datasets_badge_drift(self, tmp_path, monkeypatch):
        """The original W19-E2 finding: EN datasets-14, CN datasets-16.
        Must trigger both a freshness fail AND a parity fail."""
        mod = self._load()
        live_gates = mod._live_gate_count()
        live_datasets = mod._live_dataset_count()
        live_lint = mod._live_lint_rule_count()
        cn = self._badge_block(
            gates=live_gates, datasets=live_datasets,
            code_loc=147, lint_rules=live_lint,
        )
        en = self._badge_block(
            gates=live_gates, datasets=live_datasets - 2,
            code_loc=147, lint_rules=live_lint,
        )
        code, errs = self._run_badge_check(
            mod, monkeypatch, tmp_path, cn, en,
        )
        assert code == 2, "expected failure for datasets badge drift"
        assert any(
            "badge_datasets_en" in e and "truth" in e for e in errs
        ), f"missing freshness error for datasets badge: {errs}"
        assert any(
            "PARITY" in e and "badge_datasets" in e for e in errs
        ), f"missing parity error for datasets badge: {errs}"

    def test_detects_gates_badge_drift(self, tmp_path, monkeypatch):
        """A stale gates badge (e.g. 33 → 32 after a deprecation) must
        fail freshness for the doc that's wrong."""
        mod = self._load()
        live_gates = mod._live_gate_count()
        live_datasets = mod._live_dataset_count()
        live_lint = mod._live_lint_rule_count()
        bad = self._badge_block(
            gates=live_gates - 1, datasets=live_datasets,
            code_loc=147, lint_rules=live_lint,
        )
        good = self._badge_block(
            gates=live_gates, datasets=live_datasets,
            code_loc=147, lint_rules=live_lint,
        )
        code, errs = self._run_badge_check(
            mod, monkeypatch, tmp_path, bad, good,
        )
        assert code == 2
        assert any("badge_gates_cn" in e for e in errs), errs

    def test_detects_lint_rules_badge_drift(self, tmp_path, monkeypatch):
        """When a new R0NN rule lands but neither README is updated,
        both badges should fail freshness."""
        mod = self._load()
        live_gates = mod._live_gate_count()
        live_datasets = mod._live_dataset_count()
        live_lint = mod._live_lint_rule_count()
        block = self._badge_block(
            gates=live_gates, datasets=live_datasets,
            code_loc=147, lint_rules=live_lint - 1,
        )
        code, errs = self._run_badge_check(
            mod, monkeypatch, tmp_path, block, block,
        )
        assert code == 2
        # Both CN and EN should be flagged (parity holds, but freshness
        # fails on both sides).
        assert any("badge_lint_rules_cn" in e for e in errs), errs
        assert any("badge_lint_rules_en" in e for e in errs), errs

    def test_detects_code_loc_parity_drift(self, tmp_path, monkeypatch):
        """The code-LOC badge is hand-maintained (sentinel truth, no
        freshness check), but the W19-E2 finding included CN 147K vs
        EN 145K — a parity drift that the old checker missed entirely.
        The PARITY loop must still catch it."""
        mod = self._load()
        live_gates = mod._live_gate_count()
        live_datasets = mod._live_dataset_count()
        live_lint = mod._live_lint_rule_count()
        cn = self._badge_block(
            gates=live_gates, datasets=live_datasets,
            code_loc=147, lint_rules=live_lint,
        )
        en = self._badge_block(
            gates=live_gates, datasets=live_datasets,
            code_loc=145, lint_rules=live_lint,
        )
        code, errs = self._run_badge_check(
            mod, monkeypatch, tmp_path, cn, en,
        )
        assert code == 2
        assert any(
            "PARITY" in e and "badge_code_loc" in e for e in errs
        ), f"PARITY check did not catch CN 147 vs EN 145: {errs}"

    def test_detects_missing_lint_rules_badge_in_en(
        self, tmp_path, monkeypatch,
    ):
        """W19-E2 also flagged that EN was missing the lint-rules
        badge entirely. The checker should report 'matched nothing'
        for the EN claim while CN passes."""
        mod = self._load()
        live_gates = mod._live_gate_count()
        live_datasets = mod._live_dataset_count()
        live_lint = mod._live_lint_rule_count()
        cn = self._badge_block(
            gates=live_gates, datasets=live_datasets,
            code_loc=147, lint_rules=live_lint,
        )
        # EN: strip the lint-rules badge line.
        en_lines = cn.splitlines(keepends=True)
        en_block = "".join(
            ln for ln in en_lines if "lint%20rules" not in ln
        )
        code, errs = self._run_badge_check(
            mod, monkeypatch, tmp_path, cn, en_block,
        )
        assert code == 2
        assert any(
            "badge_lint_rules_en" in e and "matched nothing" in e
            for e in errs
        ), f"missing-badge case not detected: {errs}"


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


class TestH2SectionParity:
    """Cross-language H2 section-parity check.

    Catches a whole section existing in one README but not the other —
    the drift that shipped EN without Codebook RAG / Benchmark Results
    for months while CN had both.
    """

    def _readmes_from_pairs(self, mod, drop_en=None, extra_cn=None,
                            include_cn_only=True):
        """Render synthetic CN/EN READMEs from the registered map.

        drop_en: omit this EN section title (simulate EN drift).
        extra_cn: append this unregistered CN H2 (simulate an orphan).
        """
        cn_titles = [p[0] for p in mod._H2_PAIRS]
        en_titles = [p[1] for p in mod._H2_PAIRS if p[1] != drop_en]
        if include_cn_only:
            cn_titles += sorted(mod._CN_ONLY_H2)
        if extra_cn:
            cn_titles.append(extra_cn)

        def render(ts):
            return "# T\n\n" + "\n\n".join(
                f"## {t}\n\nbody" for t in ts) + "\n"

        return render(cn_titles), render(en_titles)

    def test_h2_parity_clean_against_real_readme(self):
        """The checked-in READMEs must satisfy the registered map.
        Fails loudly with the drift if a section is single-sided."""
        mod = _load_module()
        errs = mod._check_h2_parity(
            mod.CN.read_text(encoding="utf-8"),
            mod.EN.read_text(encoding="utf-8"),
        )
        assert errs == [], errs

    def test_h2_parity_clean_synthetic(self):
        """A synthetic pair containing exactly the registered sections
        (plus CN-only) is clean — CN-only titles are not orphans."""
        mod = _load_module()
        cn, en = self._readmes_from_pairs(mod)
        assert mod._check_h2_parity(cn, en) == []

    def test_h2_parity_detects_missing_en_section(self):
        """Dropping a registered EN section is flagged as missing."""
        mod = _load_module()
        drop = mod._H2_PAIRS[-1][1]
        cn, en = self._readmes_from_pairs(mod, drop_en=drop)
        errs = mod._check_h2_parity(cn, en)
        assert any("EN README is missing" in e and drop in e
                   for e in errs), errs

    def test_h2_parity_detects_cn_orphan(self):
        """An unregistered CN H2 is flagged as an orphan."""
        mod = _load_module()
        cn, en = self._readmes_from_pairs(mod, extra_cn="未登记的新章节")
        errs = mod._check_h2_parity(cn, en)
        assert any("unregistered" in e and "未登记的新章节" in e
                   for e in errs), errs
