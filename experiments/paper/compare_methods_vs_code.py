#!/usr/bin/env python3
"""
Compare Methods-section review (Qwen) vs code review (Claude) results.

Identifies:
1. Papers where Methods claims are inconsistent with code reality
2. Leakage types detected by each method
3. Agreement/disagreement statistics

Usage:
  python3 experiments/paper/compare_methods_vs_code.py \
    --methods-dir experiments/paper/output/llm_reviews/ \
    --audit-log experiments/paper/manual_audit_log.jsonl \
    --blind-list experiments/paper/blind_audit_list.jsonl \
    --output experiments/paper/output/methods_vs_code_comparison.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def load_methods_reviews(review_dir: Path) -> Dict[str, dict]:
    """Load per-paper Qwen reviews."""
    reviews = {}
    for f in review_dir.glob("PMC*.json"):
        with f.open() as fh:
            r = json.load(fh)
        if r.get("status") == "reviewed":
            reviews[r["pmcid"]] = r
    return reviews


def load_code_audits(audit_log: Path, blind_list: Path) -> Dict[str, dict]:
    """Load code audit verdicts, keyed by PMC ID."""
    # Load blind list to get paper_id -> pmcid mapping
    papers_verified = {}
    verified_path = blind_list.parent / "papers_verified_v2.jsonl"
    if verified_path.exists():
        with verified_path.open() as f:
            for line in f:
                if line.strip():
                    p = json.loads(line)
                    papers_verified[p["paper_id"]] = p

    # Load blind list for paper_id set
    blind_ids = set()
    with blind_list.open() as f:
        for line in f:
            if line.strip():
                blind_ids.add(json.loads(line)["paper_id"])

    # Load audit log
    audits = {}
    by_paper: Dict[str, dict] = {}
    with audit_log.open() as f:
        for line in f:
            if line.strip():
                e = json.loads(line)
                pid = e["paper_id"]
                if pid not in blind_ids:
                    continue
                if pid not in by_paper or e["audit_id"] > by_paper[pid]["audit_id"]:
                    by_paper[pid] = e

    for pid, e in by_paper.items():
        pmcid = papers_verified.get(pid, {}).get("pmcid", "")
        if pmcid:
            audits[pmcid] = e

    return audits


def compare(
    methods_reviews: Dict[str, dict],
    code_audits: Dict[str, dict],
) -> dict:
    """Compare Methods review vs code audit."""
    matched = []
    methods_only = []
    code_only = []

    all_pmcids = set(methods_reviews.keys()) | set(code_audits.keys())

    for pmcid in sorted(all_pmcids):
        mr = methods_reviews.get(pmcid)
        ca = code_audits.get(pmcid)

        if mr and ca:
            matched.append((pmcid, mr, ca))
        elif mr and not ca:
            methods_only.append(pmcid)
        elif ca and not mr:
            code_only.append(pmcid)

    # Analyze matched pairs
    comparisons = []
    agreement_count = 0
    disagreement_count = 0
    methods_leakage_types = Counter()
    code_leakage_types = Counter()
    contradiction_cases = []

    for pmcid, mr, ca in matched:
        # Methods verdict
        methods_flags = set(mr.get("leakage_flags", []))
        methods_has_leak = bool(methods_flags)
        methods_score = mr.get("overall_score", 0)

        # Code verdict
        r2_raw = ca.get("r2_verdict", ca.get("human_verdict", ""))
        code_has_leak = r2_raw in ("YES", "TP_confirmed", "FN_missed_real_leak")
        code_flags = set(ca.get("kapoor_types", []))

        # Normalize code flags to match Methods format (L1.2, L3.2, etc.)
        code_flags_normalized = set()
        for cf in code_flags:
            # e.g., "L1.2_preprocessing_on_full" -> "L1.2"
            parts = cf.split("_", 1)
            if parts[0].startswith("L"):
                code_flags_normalized.add(parts[0])

        # Agreement
        agree = methods_has_leak == code_has_leak
        if agree:
            agreement_count += 1
        else:
            disagreement_count += 1

        # Track types
        for f in methods_flags:
            methods_leakage_types[f] += 1
        for f in code_flags_normalized:
            code_leakage_types[f] += 1

        # Contradiction analysis
        comp = {
            "pmcid": pmcid,
            "paper_id": ca.get("paper_id", ""),
            "methods_has_leakage": methods_has_leak,
            "methods_score": methods_score,
            "methods_flags": sorted(methods_flags),
            "code_has_leakage": code_has_leak,
            "code_flags": sorted(code_flags_normalized),
            "agreement": agree,
        }

        if not agree:
            if methods_has_leak and not code_has_leak:
                comp["contradiction_type"] = "methods_only"
                comp["interpretation"] = (
                    "Methods section raises concerns but code appears clean. "
                    "Possible: Methods is vague/ambiguous, or code implements "
                    "correctly despite poor description."
                )
            else:
                comp["contradiction_type"] = "code_only"
                comp["interpretation"] = (
                    "Code has leakage but Methods description doesn't reveal it. "
                    "This is the dangerous case: paper looks clean on paper review "
                    "but has hidden implementation flaws."
                )
            contradiction_cases.append(comp)

        comparisons.append(comp)

    n_matched = len(matched)
    methods_leaky = sum(1 for _, mr, _ in matched if mr.get("leakage_flags"))
    code_leaky = sum(1 for _, _, ca in matched
                     if ca.get("r2_verdict", ca.get("human_verdict", ""))
                     in ("YES", "TP_confirmed", "FN_missed_real_leak"))

    return {
        "summary": {
            "n_matched": n_matched,
            "n_methods_only": len(methods_only),
            "n_code_only": len(code_only),
            "agreement_rate": round(agreement_count / n_matched, 3) if n_matched else 0,
            "disagreement_count": disagreement_count,
            "methods_leakage_prevalence": f"{methods_leaky}/{n_matched}",
            "code_leakage_prevalence": f"{code_leaky}/{n_matched}",
        },
        "methods_leakage_types": dict(methods_leakage_types.most_common()),
        "code_leakage_types": dict(code_leakage_types.most_common()),
        "contradiction_cases": contradiction_cases,
        "comparisons": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Methods vs Code review.")
    parser.add_argument("--methods-dir", required=True, help="Dir with Qwen review JSONs.")
    parser.add_argument("--audit-log", required=True, help="manual_audit_log.jsonl")
    parser.add_argument("--blind-list", required=True, help="blind_audit_list.jsonl")
    parser.add_argument("--output", required=True, help="Output JSON.")
    args = parser.parse_args()

    mr = load_methods_reviews(Path(args.methods_dir))
    ca = load_code_audits(Path(args.audit_log), Path(args.blind_list))

    print(f"Methods reviews loaded: {len(mr)}", file=sys.stderr)
    print(f"Code audits loaded: {len(ca)}", file=sys.stderr)

    result = compare(mr, ca)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    s = result["summary"]
    print(f"\n{'='*50}")
    print(f"Matched: {s['n_matched']} papers")
    print(f"Agreement: {s['agreement_rate']*100:.1f}%")
    print(f"Methods leakage: {s['methods_leakage_prevalence']}")
    print(f"Code leakage: {s['code_leakage_prevalence']}")
    print(f"Contradictions: {s['disagreement_count']}")
    print(f"\nMethods types: {result['methods_leakage_types']}")
    print(f"Code types: {result['code_leakage_types']}")

    if result["contradiction_cases"]:
        print(f"\n--- Contradictions ---")
        for c in result["contradiction_cases"][:5]:
            print(f"  {c['pmcid']} ({c['paper_id']}): {c['contradiction_type']}")
            print(f"    Methods flags: {c['methods_flags']}")
            print(f"    Code flags: {c['code_flags']}")

    print(f"\nOutput: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
