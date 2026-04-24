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


def _live_kb_stats() -> Tuple[int, int]:
    """Return (paper_count, concern_count) from the live KB."""
    kb = json.loads(KB.read_text(encoding="utf-8"))
    entries = kb.get("entries", [])
    papers = len(entries)
    concerns = sum(
        len(e.get("reviewer_concerns", []) or [])
        for e in entries
        if isinstance(e, dict)
    )
    return papers, concerns


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
    "codebooks", "review", "diagnostics", "orchestration",
]


def _live_scripts_subdir_counts() -> Dict[str, Tuple[int, int]]:
    """Return {subdir: (count_excl_init, count_incl_init)} for scripts/*/."""
    counts: Dict[str, Tuple[int, int]] = {}
    for d in _SUBDIRS:
        path = ROOT / "scripts" / d
        pyfiles = list(path.glob("*.py")) if path.is_dir() else []
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
    return {
        "total":    len(list(tests.glob("test_*.py"))),
        "gate":     len(list(tests.glob("test_*_gate.py"))),
        "e2e":      len(list(tests.glob("test_*e2e*.py"))),
        "stress":   len(list(tests.glob("test_stress*.py"))),
        "security": len(list(tests.glob("test_security*.py"))),
    }


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

    return claims


# Patterns keyed by (claim_name, pattern, fmt). The pattern MUST capture
# exactly one integer. fmt is "cn" / "en" / "both" — where to check.
# Each entry carries a short description for the error message.
_CLAIMS: List[Dict[str, object]] = [
    # NC papers count
    {
        "name": "nc_papers_cn",
        "doc": CN,
        "regex": r"(\d{2,4})\s*篇\s*NC\s*审稿证据",
        "source": "kb_papers",
        "description": "CN tagline 'NN 篇 NC 审稿证据'",
    },
    {
        "name": "nc_papers_en",
        "doc": EN,
        "regex": r"(\d{2,4})\s*NC\s*Peer\s*Review\s*Evidence",
        "source": "kb_papers",
        "description": "EN tagline 'NN NC Peer Review Evidence'",
    },
    {
        "name": "nc_papers_cn_mission",
        "doc": CN,
        "regex": r"(\d{2,4})\s*篇\s*Nature Communications\s*真实审稿意见",
        "source": "kb_papers",
        "description": "CN mission statement",
    },
    {
        "name": "nc_papers_en_mission",
        "doc": EN,
        "regex": r"(\d{2,4})\s*real\s*Nature\s*Communications\s*peer\s*review\s*opinions",
        "source": "kb_papers",
        "description": "EN mission statement",
    },
    # Concerns count
    {
        "name": "concerns_cn",
        "doc": CN,
        "regex": r"(\d{2,4})\s*条\s*结构化审稿意见",
        "source": "kb_concerns",
        "description": "CN detailed '452 条结构化审稿意见'",
    },
    {
        "name": "concerns_en",
        "doc": EN,
        "regex": r"(\d{2,4})\s*structured\s*review\s*opinions",
        "source": "kb_concerns",
        "description": "EN detailed '452 structured review opinions'",
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

    papers, concerns = _live_kb_stats()
    gates = _live_gate_count()
    subdirs = _live_scripts_subdir_counts()
    tests = _live_tests_counts()

    truth: Dict[str, int] = {
        "kb_papers": papers,
        "kb_concerns": concerns,
        "gate_count": gates,
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

        where = "CN" if doc == CN else "EN"
        name = str(claim["name"])
        if actual is None:
            errors.append(
                f"[{where}] {name}: pattern '{regex}' matched nothing — "
                f"{claim['description']} may have been rephrased. Update "
                f"the regex in check_readme_stats.py or restore the claim."
            )
            continue
        if actual != expected:
            errors.append(
                f"[{where}] {name}: README says {actual}, truth is "
                f"{expected} ({claim['description']})"
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
        papers, concerns = _live_kb_stats()
        gates = _live_gate_count()
        subdirs = _live_scripts_subdir_counts()
        tests = _live_tests_counts()
        print("OK: CN/EN agree; live truth:")
        print(f"  KB:     {papers} papers, {concerns} concerns, {gates} gates")
        print(f"  scripts/ subdirs (excl __init__ / incl __init__):")
        for d, (excl, incl) in subdirs.items():
            print(f"    {d:15s} {excl:3d} / {incl:3d}")
        print(f"  tests/:  total={tests['total']}, gate={tests['gate']}, "
              f"e2e={tests['e2e']}, stress={tests['stress']}, "
              f"security={tests['security']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
