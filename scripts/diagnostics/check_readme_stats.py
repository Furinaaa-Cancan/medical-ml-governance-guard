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

        # Skip this claim entirely when the live truth is the sentinel
        # value (e.g. MLGG_CHECK_PYTEST_COUNT=0 → pytest_count=-1).
        skip_when = claim.get("skip_when")
        if skip_when is not None and expected == skip_when:
            continue

        tolerance = int(claim.get("tolerance") or 0)  # type: ignore[arg-type]

        where = "CN" if doc == CN else "EN"
        name = str(claim["name"])
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
        if where == "CN":
            cn_values[name.replace("_cn", "").replace("_mission", "")] = actual
        else:
            en_values[name.replace("_en", "").replace("_mission", "")] = actual

    # Parity: for each stat that has both CN and EN, numbers must agree.
    for key in set(cn_values) & set(en_values):
        if cn_values[key] is not None and en_values[key] is not None:
            if cn_values[key] != en_values[key]:
                errors.append(
                    f"PARITY: CN {key}={cn_values[key]} but "
                    f"EN {key}={en_values[key]} — the two READMEs disagree"
                )

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
