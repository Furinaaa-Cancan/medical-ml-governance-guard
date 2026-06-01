#!/usr/bin/env python3
"""Validate that README.md and README_EN.md quote the same, current stats.

Both READMEs are maintained side-by-side. Over time they drift: CN says
"106 NC papers", EN says "107", the live KB has 119. This script is the
automated parity + freshness check for the numeric claims that are
easiest to silently regress.

For each numeric claim we check:
- CN and EN quote the same number (parity)
- The number matches live ground truth (freshness), either computed
  from the source KB or pytest collection

Exit 0 on all clean, 2 on any mismatch. Intended for pre-commit +
ci-unit.

Usage:
    python3 scripts/diagnostics/check_readme_stats.py
    python3 scripts/diagnostics/check_readme_stats.py --verbose
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
CN = ROOT / "README.md"
EN = ROOT / "README_EN.md"
KB = ROOT / "references" / "case-studies" / "peer-review-kb.json"


def _live_kb_stats() -> Tuple[int, int, int]:
    """Return (paper_count, concern_count, curated_count) from the live KB.

    curated_count is the subset of entries with a non-empty
    reviewer_concerns array — i.e., papers where a reviewer has actually
    extracted structured concerns. The remainder are catalog entries
    whose PDFs are linked but whose review text has not yet been
    audited (e.g., OpenAlex-discovered PR-EXP-NNNN entries flagged
    `data_type=pending_metadata_extraction`).

    Documenting both numbers keeps publication-grade claims honest:
    paper count = catalog size; curated count = actual evidence base.
    """
    kb = json.loads(KB.read_text(encoding="utf-8"))
    entries = kb.get("entries", [])
    papers = len(entries)
    concerns = sum(
        len(e.get("reviewer_concerns", []) or [])
        for e in entries
        if isinstance(e, dict)
    )
    curated = sum(
        1 for e in entries
        if isinstance(e, dict) and (e.get("reviewer_concerns") or [])
    )
    return papers, concerns, curated


def _live_gate_count() -> int:
    """Return the number of registered gates (authoritative)."""
    sys.path.insert(0, str(ROOT / "scripts" / "core"))
    try:
        from _gate_registry import GATE_REGISTRY  # type: ignore
    finally:
        sys.path.pop(0)
    return len(GATE_REGISTRY)


# ── Project structure drift detection ───────────────────────────────
# The README project-structure section drifts faster than any other
# piece of the doc — every parallel session adds files. Catching it
# at pre-commit saves us the "oh the README says 9 diagnostics/ files
# but there are 15" embarrassment.
#
# CN convention: "core/ (6 files, 7.0K LOC)" — excludes __init__.py
# EN convention: "core/ (7)"                  — includes __init__.py
# Both are checked independently so the two doc styles can coexist.

_SUBDIRS: List[str] = [
    "core", "gates", "training", "reporting",
    "codebooks", "review", "diagnostics", "orchestration", "rag",
]


def _live_scripts_subdir_counts() -> Dict[str, Tuple[int, int]]:
    """Return {subdir: (count_excl_init, count_incl_init)} for scripts/*/.

    Excludes dot-prefixed files (macOS AppleDouble metadata "._foo.py"
    siblings on external volumes). Without this, drift counts diverge
    between dev (4+ extra "files") and CI (no AppleDouble), and the
    README ends up perpetually wrong on one of the two.
    """
    counts: Dict[str, Tuple[int, int]] = {}
    for d in _SUBDIRS:
        path = ROOT / "scripts" / d
        pyfiles = (
            [p for p in path.glob("*.py") if not p.name.startswith(".")]
            if path.is_dir()
            else []
        )
        counts[d] = (
            sum(1 for p in pyfiles if p.name != "__init__.py"),
            len(pyfiles),
        )
    return counts


def _live_tests_counts() -> Dict[str, int]:
    """Return file-count snapshots for tests/ patterns cited in both READMEs.

    Globs stay aligned with the README tree (test_*_gate.py, test_*_e2e.py,
    test_stress_*.py, test_security*.py plus total test_*.py).
    """
    tests = ROOT / "tests"
    if not tests.is_dir():
        return {k: 0 for k in ("total", "gate", "e2e", "stress", "security")}
    # Exclude AppleDouble dotfiles ("._test_foo.py") for the same reason
    # as _live_scripts_subdir_counts above.
    def _glob(pattern: str) -> list:
        return [p for p in tests.glob(pattern) if not p.name.startswith(".")]
    return {
        "total":    len(_glob("test_*.py")),
        "gate":     len(_glob("test_*_gate.py")),
        "e2e":      len(_glob("test_*e2e*.py")),
        "stress":   len(_glob("test_stress*.py")),
        "security": len(_glob("test_security*.py")),
    }


def _live_skill_md_lines() -> int:
    """Current SKILL.md line count. Cited in both READMEs under the
    '≤ 500 lines' engineering-guarantee bullet."""
    p = ROOT / "SKILL.md"
    if not p.exists():
        return 0
    return len(p.read_text(encoding="utf-8").splitlines())


def _live_curated_references_mb() -> int:
    """Size of human-curated references content (JSON/YAML/MD/TXT only).

    Excludes generated SQLite DBs and PDF source papers because those
    are bulky artifacts, not 'curated' knowledge. Also excludes
    gitignored content (e.g. references/case-studies/nature_communications/
    text/*.txt — paper full-texts kept locally but not committed for
    copyright reasons): without this filter, the script reports ~30 MB
    on dev machines that have downloaded the texts but ~2 MB on CI
    runners (clean clones), which makes the README pernamenently
    drift in one direction or the other.

    Uses `git ls-files` for authority — same number on dev and CI
    regardless of what extra files happen to sit in the working tree.
    Falls back to filesystem rglob if git is unavailable (e.g. running
    from a tarball release).
    """
    refs = ROOT / "references"
    if not refs.is_dir():
        return 0
    total = 0
    try:
        import subprocess
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "references/"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        tracked = [
            ROOT / line.strip()
            for line in result.stdout.splitlines()
            if line.strip().endswith((".json", ".yaml", ".md", ".txt"))
        ]
        for p in tracked:
            try:
                total += p.stat().st_size
            except OSError:
                pass
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        # No git available — fall back to filesystem walk.
        for ext in ("*.json", "*.yaml", "*.md", "*.txt"):
            for p in refs.rglob(ext):
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    return round(total / (1024 * 1024))


def _live_dataset_count() -> int:
    """Return the count of medical example CSV datasets shipped under
    ``examples/``. This backs the README header badge
    ``datasets-NN%20medical-purple``.

    Source of truth (in order):

    1. ``examples/README.md`` header ``## 1. 医学数据集 (`*.csv`, N 个)``
       — the authoritative catalog count maintained alongside the
       per-dataset table. This survives sparse CI checkouts where
       only one CSV (``brfss2022_aligned.csv``) is git-tracked and
       the other 15 are produced on-demand by ``download_*.py``
       scripts (W28-V1 fix: filesystem glob returned 1 on CI, 16
       locally, causing README parity to flap).
    2. Filesystem glob over ``examples/*.csv`` — historical fallback.
       Counted at the top level only; synthetic sub-fixtures under
       ``tests/fixtures/`` are not user-facing example data.
    """
    catalog = ROOT / "examples" / "README.md"
    if catalog.is_file():
        text = catalog.read_text(encoding="utf-8", errors="ignore")
        # Header format example: "## 1. 医学数据集 (`*.csv`, 16 个)"
        m = re.search(r"医学数据集.*?(\d+)\s*个", text)
        if m:
            return int(m.group(1))
    ex = ROOT / "examples"
    if not ex.is_dir():
        return 0
    return sum(
        1 for p in ex.glob("*.csv") if not p.name.startswith(".")
    )


def _live_lint_rule_count() -> int:
    """Return the count of registered ``mlgg_lint`` rule classes.

    Authoritative source = the rules registry built by importing every
    ``plugin/mlgg_lint/rules/r*.py`` module. This guarantees the badge
    tracks the actually-loadable rule set, not just the file count
    (which can drift via abandoned/stub files).

    Falls back to a file-count over ``plugin/mlgg_lint/rules/r*.py``
    when the plugin can't be imported (e.g. clean clone before
    ``pip install -e plugin/``).
    """
    plugin_path = ROOT / "plugin"
    inserted = False
    if plugin_path.is_dir():
        sys.path.insert(0, str(plugin_path))
        inserted = True
    try:
        from mlgg_lint.rules import get_all_rules  # type: ignore
        return len(get_all_rules())
    except Exception:
        # Fall back to file count: r*.py modules in the rules dir.
        rules_dir = plugin_path / "mlgg_lint" / "rules"
        if not rules_dir.is_dir():
            return 0
        return sum(
            1 for p in rules_dir.glob("r*.py")
            if not p.name.startswith(".")
        )
    finally:
        if inserted:
            try:
                sys.path.remove(str(plugin_path))
            except ValueError:
                pass


def _live_pytest_collect_count() -> int:
    """Authoritative pytest test count via `--collect-only`. Used for
    the README header badge `tests-NNNN passed`.

    Slow-ish (~4s), so the check is opt-in via env var to keep
    pre-commit snappy. When `MLGG_CHECK_PYTEST_COUNT=1`, the live
    value is computed; otherwise this returns -1 and the badge
    claim is skipped.
    """
    import os
    import subprocess
    if os.environ.get("MLGG_CHECK_PYTEST_COUNT") != "1":
        return -1
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q",
             "tests/", "plugin/tests/"],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return -1
    match = re.search(r"(\d+)\s+tests?\s+collected", proc.stdout)
    return int(match.group(1)) if match else -1


def _build_structure_claims() -> List[Dict[str, object]]:
    """Generate the structure-tree claim list procedurally.

    One claim per (subdir, doc) for scripts/*/, one per (pattern, doc)
    for tests/*. 2 × 8 + 2 × 5 = 26 claims.
    """
    claims: List[Dict[str, object]] = []

    for d in _SUBDIRS:
        # CN: "├── core/              (6 files, 7.0K LOC)"
        #     excludes __init__.py; regex captures first number before "files"
        claims.append({
            "name": f"scripts_{d}_excl_cn",
            "doc": CN,
            "regex": rf"── {d}/\s+\((\d+)\s*files",
            "source": f"scripts_{d}_excl",
            "description": f"CN scripts/{d}/ file count (excl __init__)",
        })
        # EN: "├── core/              (7)"  (includes __init__.py)
        claims.append({
            "name": f"scripts_{d}_incl_en",
            "doc": EN,
            "regex": rf"── {d}/\s+\((\d+)\)",
            "source": f"scripts_{d}_incl",
            "description": f"EN scripts/{d}/ file count (incl __init__)",
        })

    # tests/ - same number in CN and EN (parity check kicks in naturally)
    tests_patterns = [
        ("total",    r"── tests/\s+\((\d+)\)",             "tests/ total file count"),
        ("gate",     r"test_\*_gate\.py\s+\((\d+)\)",      "test_*_gate.py count"),
        ("e2e",      r"test_\*_e2e\.py\s+\((\d+)\)",       "test_*_e2e.py count"),
        ("stress",   r"test_stress_\*\.py\s+\((\d+)\)",    "test_stress_*.py count"),
        ("security", r"test_security\*\.py\s+\((\d+)\)",   "test_security*.py count"),
    ]
    for key, regex, desc in tests_patterns:
        for doc, where in ((CN, "cn"), (EN, "en")):
            claims.append({
                "name": f"tests_{key}_{where}",
                "doc": doc,
                "regex": regex,
                "source": f"tests_{key}",
                "description": f"{where.upper()} tests tree: {desc}",
            })

    # SKILL.md line count — cited in both READMEs' "engineering
    # guarantees" bullet as "currently NNN lines". Claude Code
    # recommends <500 lines; we're tracking to catch unexpected growth.
    claims.append({
        "name": "skill_md_lines_cn",
        "doc": CN,
        "regex": r"当前\s*(\d+)\s*行，符合 Claude Code 官方",
        "source": "skill_md_lines",
        "description": "CN SKILL.md current-line claim",
    })
    claims.append({
        "name": "skill_md_lines_en",
        "doc": EN,
        "regex": r"currently\s*(\d+)\s*lines,\s*within\s+Claude\s+Code",
        "source": "skill_md_lines",
        "description": "EN SKILL.md current-line claim",
    })

    # references/ curated size — the "~NN MB human-curated" label in
    # the architecture diagram. Tolerance: ±10 MB (any single PR can
    # reasonably move curated KB by a few MB without it being drift).
    claims.append({
        "name": "refs_curated_mb_cn",
        "doc": CN,
        "regex": r"references/\s+~(\d+)\s*MB human-curated",
        "source": "refs_curated_mb",
        "description": "CN references/ '~NN MB human-curated' label",
        "tolerance": 10,
    })
    claims.append({
        "name": "refs_curated_mb_en",
        "doc": EN,
        "regex": r"references/\s+~(\d+)\s*MB human-curated",
        "source": "refs_curated_mb",
        "description": "EN references/ '~NN MB human-curated' label",
        "tolerance": 10,
    })

    # Pytest test count in the header badge. Only enforced when the
    # env var MLGG_CHECK_PYTEST_COUNT=1 is set (test collection is
    # ~4s which makes pre-commit slow if always on). Tolerance ±100
    # so typical PR-level test adds/removes don't trigger drift on
    # the rounded badge number.
    claims.append({
        "name": "pytest_count_cn",
        "doc": CN,
        "regex": r"tests-(\d+)%20passed-brightgreen",
        "source": "pytest_count",
        "description": "CN header badge 'tests-NNNN passed'",
        "tolerance": 100,
        "skip_when": -1,
    })
    claims.append({
        "name": "pytest_count_en",
        "doc": EN,
        "regex": r"tests-(\d+)%20passed-brightgreen",
        "source": "pytest_count",
        "description": "EN header badge 'tests-NNNN passed'",
        "tolerance": 100,
        "skip_when": -1,
    })

    # ── Header badges (W20-F5) ─────────────────────────────────────
    # CN and EN both ship a row of shields.io badges in the page
    # header. Before W20-F5 only `tests-` was checked; EN drifted to
    # `datasets-14` while CN said 16 (truth: 16 CSVs in examples/),
    # and EN was silently missing the lint-rules badge entirely.
    # The four claims below cover every numeric header badge in both
    # READMEs; freshness fires on missing/stale values, parity fires
    # automatically via the shared name-suffix logic in check().
    #
    # The badge URL format is `badge/<label>-<value>-<color>` where
    # `--` in the URL decodes to a literal `-` in the label, so the
    # regex anchors on the value position with a non-greedy lead.

    # gates-NN%20fail--closed → registered gate count
    claims.append({
        "name": "badge_gates_cn",
        "doc": CN,
        "regex": r"badge/gates-(\d+)%20fail--closed",
        "source": "gate_count",
        "description": "CN header badge 'gates-NN fail-closed'",
    })
    claims.append({
        "name": "badge_gates_en",
        "doc": EN,
        "regex": r"badge/gates-(\d+)%20fail--closed",
        "source": "gate_count",
        "description": "EN header badge 'gates-NN fail-closed'",
    })

    # datasets-NN%20medical → examples/*.csv count
    claims.append({
        "name": "badge_datasets_cn",
        "doc": CN,
        "regex": r"badge/datasets-(\d+)%20medical",
        "source": "dataset_count",
        "description": "CN header badge 'datasets-NN medical'",
    })
    claims.append({
        "name": "badge_datasets_en",
        "doc": EN,
        "regex": r"badge/datasets-(\d+)%20medical",
        "source": "dataset_count",
        "description": "EN header badge 'datasets-NN medical'",
    })

    # lint%20rules-NN%20(R001--R0NN) → registered rule count
    claims.append({
        "name": "badge_lint_rules_cn",
        "doc": CN,
        "regex": r"badge/lint%20rules-(\d+)%20",
        "source": "lint_rule_count",
        "description": "CN header badge 'lint rules-NN'",
    })
    claims.append({
        "name": "badge_lint_rules_en",
        "doc": EN,
        "regex": r"badge/lint%20rules-(\d+)%20",
        "source": "lint_rule_count",
        "description": "EN header badge 'lint rules-NN'",
    })

    # code-NNNK%20lines → rough total Python LOC across the project.
    # Hand-maintained (rounded thousands). The badge value is a human
    # choice, not derivable from a single authoritative computation
    # (scripts/ vs scripts+plugin+tests vs git-ls-files all diverge
    # by tens of thousands). The "truth" is a sentinel (-1) so the
    # freshness branch short-circuits via skip_when; the PARITY loop
    # downstream still catches CN/EN drift — the W19-E2 finding was
    # CN 147K vs EN 145K, which the old checker missed entirely.
    claims.append({
        "name": "badge_code_loc_cn",
        "doc": CN,
        "regex": r"badge/code-(\d+)K%20lines",
        "source": "code_loc_k",
        "description": "CN header badge 'code-NNNK lines'",
        "skip_when": -1,
    })
    claims.append({
        "name": "badge_code_loc_en",
        "doc": EN,
        "regex": r"badge/code-(\d+)K%20lines",
        "source": "code_loc_k",
        "description": "EN header badge 'code-NNNK lines'",
        "skip_when": -1,
    })

    return claims


# Patterns keyed by (claim_name, pattern, fmt). The pattern MUST capture
# exactly one integer. fmt is "cn" / "en" / "both" — where to check.
# Each entry carries a short description for the error message.
_CLAIMS: List[Dict[str, object]] = [
    # Total NC+CM peer-review PDFs in catalog (kb_papers, currently 335).
    # The phrase "NC+CM 同行评审 PDF" intentionally avoids the older
    # "审稿证据" / "Peer Review Evidence" labels, which conflated
    # cataloged PDFs with audited reviews — most catalog entries are
    # OpenAlex-discovered metadata only.
    {
        "name": "nc_papers_cn",
        "doc": CN,
        "regex": r"(\d{2,4})\s*篇\s*NC\+CM\s*同行评审\s*PDF",
        "source": "kb_papers",
        "description": "CN tagline 'NN 篇 NC+CM 同行评审 PDF'",
    },
    {
        "name": "nc_papers_en",
        "doc": EN,
        "regex": r"(\d{2,4})\s*NC\+CM\s*Peer\s*Review\s*PDFs",
        "source": "kb_papers",
        "description": "EN tagline 'NN NC+CM Peer Review PDFs'",
    },
    # Curated subset with extracted reviewer_concerns (kb_curated,
    # currently 105). This is the honest "evidence base" number.
    {
        "name": "curated_cn",
        "doc": CN,
        "regex": r"(\d{2,4})\s*篇\s*已抽审稿意见",
        "source": "kb_curated",
        "description": "CN tagline 'NN 篇已抽审稿意见'",
    },
    {
        "name": "curated_en",
        "doc": EN,
        "regex": r"(\d{2,4})\s*Curated\s*with\s*Concerns",
        "source": "kb_curated",
        "description": "EN tagline 'NN Curated with Concerns'",
    },
    # Mission statements — use kb_curated (the audited count) not
    # kb_papers (the catalog count). The previous mapping to kb_papers
    # over-stated the evidence base by ~3.2× (335 cataloged vs. 105
    # actually curated).
    {
        "name": "nc_papers_cn_mission",
        "doc": CN,
        "regex": r"(\d{2,4})\s*篇\s*Nature Communications[^\n。]*?真实审稿意见",
        "source": "kb_curated",
        "description": "CN mission statement (curated count)",
    },
    {
        "name": "nc_papers_en_mission",
        "doc": EN,
        "regex": r"(\d{2,4})\s*NC\+CM\s*curated\s*reviews?",
        "source": "kb_curated",
        "description": "EN mission statement (curated count)",
    },
    # Concerns count
    {
        "name": "concerns_cn",
        "doc": CN,
        "regex": r"(\d{2,4})\s*条\s*结构化审稿意见",
        "source": "kb_concerns",
        "description": "CN detailed 'NN 条结构化审稿意见'",
    },
    {
        "name": "concerns_en",
        "doc": EN,
        "regex": r"(\d{2,4})\s*structured\s*review\s*opinions",
        "source": "kb_concerns",
        "description": "EN detailed 'NN structured review opinions'",
    },
    # Gate count (should both say 33)
    {
        "name": "gates_cn",
        "doc": CN,
        "regex": r"(\d{2,3})\s*道\s*fail-closed\s*门控",
        "source": "gate_count",
        "description": "CN '33 道 fail-closed 门控'",
    },
    {
        "name": "gates_en",
        "doc": EN,
        "regex": r"(\d{2,3})\s*fail-closed\s*gates",
        "source": "gate_count",
        "description": "EN 'NN fail-closed gates'",
    },
]


# ── Doc-map drift detection ────────────────────────────────────────
# W12-A1/A2 added hand-maintained "📂 文档地图" / "Documentation Map"
# tables to both READMEs. They're already stale (CN omits the 5
# docs/reference/*.md files A2 added in EN). Without a check, every
# new docs/FOO.md silently fails to appear in the table.
#
# We extract doc paths listed in the table, compare with `find docs/
# -name '*.md'`, and flag both stale entries (in table, not on disk)
# and orphan files (on disk, not in table). The diagnostics/ dir is
# excluded — W9-D1 froze 30 hand-copied diagnoses as archive, not
# "current docs to advertise".

# Doc-map section headers — first match wins. Use a list so we can
# scan for either CN or EN heading without coupling to language.
_DOC_MAP_HEADERS: List[str] = ["## 文档地图", "## 📂 文档地图", "## Documentation Map"]

# Paths under docs/ we never expect in the table. diagnostics/ is the
# frozen W9-D1 archive (30 entries). AppleDouble dotfiles ("._foo.md")
# are macOS metadata, never real docs.
_DOC_MAP_EXCLUDE_PREFIXES: Tuple[str, ...] = ("docs/diagnostics/",)


def _extract_doc_map_paths(readme_text: str) -> Optional[set]:
    """Extract docs/*.md paths from a README's documentation-map table.

    Returns None when the section is missing entirely (so the caller
    can distinguish "no table" from "empty table"). Otherwise returns
    the set of unique docs/ paths cited in any of these forms:
      - `docs/foo.md` (backtick-quoted)
      - [docs/foo.md](docs/foo.md) (md link with path-as-text)
      - [some text](docs/foo.md) (md link with different text)
      - bare docs/foo.md or directory references like docs/adr/
    Directory references (trailing /) are kept as-is — the caller
    decides whether to expand them.
    """
    # Locate the section. Stop at the next H2 (lines starting "## ")
    # so we don't slurp the rest of the README.
    header_idx = -1
    for header in _DOC_MAP_HEADERS:
        idx = readme_text.find(header)
        if idx != -1:
            header_idx = idx
            break
    if header_idx == -1:
        return None

    # Find next top-level section to bound extraction.
    tail = readme_text[header_idx + 1:]
    next_h2 = re.search(r"\n## ", tail)
    section = tail[: next_h2.start()] if next_h2 else tail

    paths: set = set()
    # Match any docs/...md or docs/.../ reference. Covers backtick-
    # quoted, [..](..) md links, and bare paths. Strip trailing
    # punctuation that markdown link closers leave behind.
    for m in re.finditer(r"docs/[A-Za-z0-9_./-]+", section):
        path = m.group(0).rstrip(").,;:")
        # Reject obviously-truncated matches (no extension and no
        # trailing slash) — defends against future link-text changes
        # that include the prefix without a real path.
        last = path.rsplit("/", 1)[-1]
        if not (path.endswith("/") or "." in last):
            continue
        paths.add(path)
    return paths


def _find_docs_on_disk(root: Path) -> set:
    """Return docs/*.md paths (relative to root, POSIX form) on disk.

    Excludes AppleDouble dotfiles (._foo.md), and any prefix in
    _DOC_MAP_EXCLUDE_PREFIXES (frozen archive subdirs). Forward-slash
    form matches README link convention so set ops compare cleanly.
    """
    docs_dir = root / "docs"
    if not docs_dir.is_dir():
        return set()
    found: set = set()
    for p in docs_dir.rglob("*.md"):
        # Skip macOS AppleDouble dotfiles (._foo.md) AND underscore-
        # prefixed source files (_gates_md_preamble.md is the static
        # header that generate_gates_md.py prepends — it's input to a
        # codegen, not a doc to advertise).
        if p.name.startswith(".") or p.name.startswith("_"):
            continue
        rel = p.relative_to(root).as_posix()
        if any(rel.startswith(pref) for pref in _DOC_MAP_EXCLUDE_PREFIXES):
            continue
        found.add(rel)
    return found


def _check_docs_map_drift(readme_path: Path, root: Path) -> List[str]:
    """Compare the readme's doc-map table against actual docs/ files.

    Returns a list of human-readable error strings (empty == clean).
    Two failure modes:
      - stale_in_table: README cites docs/foo.md but file is missing
      - missing_from_table: docs/foo.md exists but isn't in the table

    Directory references (e.g. `docs/adr/`) cover every file under
    that prefix — orphans there don't fire. An explicitly-cited
    directory that's empty or absent still gets flagged as stale,
    since the table claim ("ADRs live here") becomes meaningless.
    """
    where = "CN" if readme_path.name == "README.md" else "EN"
    if not readme_path.exists():
        return [f"[{where}] doc-map: {readme_path} does not exist"]

    text = readme_path.read_text(encoding="utf-8")
    cited = _extract_doc_map_paths(text)
    if cited is None:
        return [
            f"[{where}] doc-map: section header '## 📂 文档地图' / "
            f"'## Documentation Map' not found in {readme_path.name}. "
            f"The table may have been removed or renamed — restore it "
            f"or update _DOC_MAP_HEADERS in check_readme_stats.py."
        ]

    on_disk = _find_docs_on_disk(root)
    cited_files = {p for p in cited if not p.endswith("/")}
    cited_dirs = {p for p in cited if p.endswith("/")}

    # stale_in_table: cited file path doesn't exist on disk.
    stale_in_table: List[str] = []
    for path in sorted(cited_files):
        if not (root / path).is_file():
            stale_in_table.append(path)
    # Cited dirs: flag if directory itself is missing or contains no
    # non-dotfile *.md (claim "ADRs live here" no longer meaningful).
    for path in sorted(cited_dirs):
        full = root / path
        if not full.is_dir():
            stale_in_table.append(path)
            continue
        any_md = any(
            not p.name.startswith(".") for p in full.rglob("*.md")
        )
        if not any_md:
            stale_in_table.append(path)

    # missing_from_table: file on disk not covered by explicit cite
    # or by a cited directory prefix.
    def _covered_by_dir(rel: str) -> bool:
        return any(rel.startswith(d) for d in cited_dirs)

    missing_from_table = sorted(
        p for p in on_disk
        if p not in cited_files and not _covered_by_dir(p)
    )

    errors: List[str] = []
    if stale_in_table:
        errors.append(
            f"[{where}] doc-map stale_in_table: README lists "
            f"{stale_in_table} but file/dir is missing. Remove the row "
            f"from the '📂 文档地图' / 'Documentation Map' table."
        )
    if missing_from_table:
        errors.append(
            f"[{where}] doc-map missing_from_table: docs/ has "
            f"{missing_from_table} on disk but they're not in the "
            f"'📂 文档地图' / 'Documentation Map' table. Add a row per "
            f"file (or exclude via _DOC_MAP_EXCLUDE_PREFIXES if "
            f"intentionally archived)."
        )
    return errors


def check() -> Tuple[int, List[str]]:
    """Return (exit_code, error_messages)."""
    errors: List[str] = []

    papers, concerns, curated = _live_kb_stats()
    gates = _live_gate_count()
    subdirs = _live_scripts_subdir_counts()
    tests = _live_tests_counts()

    truth: Dict[str, int] = {
        "kb_papers": papers,
        "kb_concerns": concerns,
        "kb_curated": curated,
        "gate_count": gates,
        "skill_md_lines": _live_skill_md_lines(),
        "refs_curated_mb": _live_curated_references_mb(),
        "pytest_count": _live_pytest_collect_count(),
        "dataset_count": _live_dataset_count(),
        "lint_rule_count": _live_lint_rule_count(),
        # code_loc_k is a hand-rounded value with no single source of
        # truth — see _build_structure_claims() comment on the
        # badge_code_loc_* claims. The -1 sentinel lets skip_when
        # bypass freshness while parity still runs.
        "code_loc_k": -1,
    }
    for d, (excl, incl) in subdirs.items():
        truth[f"scripts_{d}_excl"] = excl
        truth[f"scripts_{d}_incl"] = incl
    for k, n in tests.items():
        truth[f"tests_{k}"] = n

    all_claims = _CLAIMS + _build_structure_claims()

    cn_values: Dict[str, Optional[int]] = {}
    en_values: Dict[str, Optional[int]] = {}

    for claim in all_claims:
        doc = claim["doc"]  # type: ignore[index]
        text = doc.read_text(encoding="utf-8")  # type: ignore[union-attr]
        regex = str(claim["regex"])
        match = re.search(regex, text)
        actual: Optional[int] = int(match.group(1)) if match else None
        expected = truth[str(claim["source"])]
        tolerance = int(claim.get("tolerance") or 0)  # type: ignore[arg-type]

        where = "CN" if doc == CN else "EN"
        name = str(claim["name"])

        # Always record CN/EN values (even when freshness is skipped)
        # so the PARITY check downstream still catches CN/EN drift.
        # Without this, sentinel-truth claims like code-LOC would
        # silently lose their parity coverage. Use a normalized key
        # (strip "_cn"/"_en"/"_mission") so the two docs share a slot.
        parity_key = (
            name
            .replace("_cn", "")
            .replace("_en", "")
            .replace("_mission", "")
        )
        if actual is not None:
            (cn_values if where == "CN" else en_values)[parity_key] = actual

        # Skip freshness when the live truth is the sentinel value
        # (e.g. MLGG_CHECK_PYTEST_COUNT=0 → pytest_count=-1, or the
        # hand-rounded code-LOC badge whose truth is intentionally
        # unenforceable). Parity has already been recorded above.
        skip_when = claim.get("skip_when")
        if skip_when is not None and expected == skip_when:
            continue

        if actual is None:
            errors.append(
                f"[{where}] {name}: pattern '{regex}' matched nothing — "
                f"{claim['description']} may have been rephrased. Update "
                f"the regex in check_readme_stats.py or restore the claim."
            )
            continue
        if abs(actual - expected) > tolerance:
            detail = (f" (tolerance ±{tolerance})" if tolerance > 0 else "")
            errors.append(
                f"[{where}] {name}: README says {actual}, truth is "
                f"{expected}{detail} ({claim['description']})"
            )

    # Parity: for each stat that has both CN and EN, numbers must agree.
    for key in set(cn_values) & set(en_values):
        if cn_values[key] is not None and en_values[key] is not None:
            if cn_values[key] != en_values[key]:
                errors.append(
                    f"PARITY: CN {key}={cn_values[key]} but "
                    f"EN {key}={en_values[key]} — the two READMEs disagree"
                )

    # Doc-map drift (W13-G2): both READMEs ship hand-maintained tables
    # of docs/*.md files. Flag stale entries + orphan files so the
    # table actually reflects reality.
    errors.extend(_check_docs_map_drift(CN, ROOT))
    errors.extend(_check_docs_map_drift(EN, ROOT))

    return (2 if errors else 0), errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    exit_code, errors = check()
    if errors:
        print("README stats drift / parity errors:\n")
        for err in errors:
            print(f"  - {err}")
        print("\nRun with --verbose after fixing to confirm.")
    elif args.verbose:
        papers, concerns, curated = _live_kb_stats()
        gates = _live_gate_count()
        subdirs = _live_scripts_subdir_counts()
        tests = _live_tests_counts()
        skill_lines = _live_skill_md_lines()
        refs_mb = _live_curated_references_mb()
        pytest_count = _live_pytest_collect_count()
        print("OK: CN/EN agree; live truth:")
        print(f"  KB:           {papers} papers ({curated} curated), {concerns} concerns, {gates} gates")
        print(f"  SKILL.md:     {skill_lines} lines")
        print(f"  refs curated: ~{refs_mb} MB (JSON/YAML/MD/TXT, excl SQLite & PDF)")
        if pytest_count >= 0:
            print(f"  pytest:       {pytest_count} tests collected")
        else:
            print("  pytest:       [skipped — set MLGG_CHECK_PYTEST_COUNT=1 to enable]")
        print("  scripts/ subdirs (excl __init__ / incl __init__):")
        for d, (excl, incl) in subdirs.items():
            print(f"    {d:15s} {excl:3d} / {incl:3d}")
        print(f"  tests/:  total={tests['total']}, gate={tests['gate']}, "
              f"e2e={tests['e2e']}, stress={tests['stress']}, "
              f"security={tests['security']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
