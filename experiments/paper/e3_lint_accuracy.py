#!/usr/bin/env python3
"""
E3: Lint rule accuracy against LLM code audit ground truth.

Cross-references MLGG lint scan results (R1, 172 repos) with
LLM code review (R2b, 41 papers) to compute per-rule PPV and sensitivity.

Usage:
  python3 experiments/paper/e3_lint_accuracy.py
"""
from __future__ import annotations

import json
from pathlib import Path
from collections import Counter

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# Mapping from MLGG lint rules to Kapoor leakage types
RULE_TO_LEAKAGE = {
    "R001": ["L1.2"],  # fit-before-split → preprocessing leakage
    "R002": ["L1.2"],  # scaler-on-test
    "R003": ["L1.2", "L2"],  # smote-on-test → resampling
    "R005": ["L1.2"],  # threshold-on-test (technically L5, but often co-occurs with L1.2)
    "R006": ["L1.3"],  # feature-selection-full
    "R007": ["L1.3"],  # target-as-feature
    "R017": ["L1.2"],  # early-stop-on-test
    "R020": ["L1.2"],  # global-clean-before-split
}

# Quality rules (not directly leakage)
QUALITY_RULES = {"R004", "R008", "R009", "R010", "R011", "R012", "R013",
                 "R014", "R015", "R016", "R018", "R019", "E000"}


def main() -> None:
    # Load R1 scan results (172 repos)
    with open(OUTPUT_DIR / "code_audit_v3_final.json") as f:
        audit = json.load(f)

    # Load R2b comparison data (43 papers with both methods + code review)
    with open(OUTPUT_DIR / "methods_vs_code_comparison.json") as f:
        comparison = json.load(f)

    # Build ground truth from R2b: pmcid → {has_leakage, code_flags}
    ground_truth = {}
    for c in comparison["comparisons"]:
        ground_truth[c["pmcid"]] = {
            "has_leakage": c["code_has_leakage"],
            "flags": c.get("code_flags", []),
        }

    # Load per-repo MLGG scan details
    # We need per-repo rule hits - check if they're in the audit file
    per_repo = audit.get("per_repo", {})

    # Load papers metadata to map paper_id → pmcid
    papers = {}
    papers_file = Path(__file__).resolve().parent / "papers_verified_v2.jsonl"
    with open(papers_file) as f:
        for line in f:
            obj = json.loads(line)
            papers[obj["pmcid"]] = obj
            papers[obj.get("paper_id", "")] = obj

    print("=" * 70)
    print("E3: MLGG LINT RULE ACCURACY vs LLM CODE AUDIT")
    print("=" * 70)

    # Overall: MLGG "any leakage rule fired" vs R2b "has_leakage"
    # We need to match PMCIDs between R1 and R2b
    matched = 0
    tp = fp = fn = tn = 0

    for pmcid, gt in ground_truth.items():
        # Check if this paper has MLGG scan results
        # The audit file uses paper_id, not pmcid directly
        paper = papers.get(pmcid, {})
        paper_id = paper.get("paper_id", "")

        # Look for per-repo data
        repo_data = per_repo.get(pmcid) or per_repo.get(paper_id)
        if repo_data is None:
            # Try matching by github_url
            continue

        matched += 1
        # Check if any leakage rule fired
        mlgg_leakage_rules = set()
        for rule_id in repo_data.get("rules_fired", []):
            if rule_id in RULE_TO_LEAKAGE:
                mlgg_leakage_rules.add(rule_id)

        mlgg_positive = len(mlgg_leakage_rules) > 0
        r2b_positive = gt["has_leakage"]

        if mlgg_positive and r2b_positive:
            tp += 1
        elif mlgg_positive and not r2b_positive:
            fp += 1
        elif not mlgg_positive and r2b_positive:
            fn += 1
        else:
            tn += 1

    print(f"\nMatched papers (in both R1 scan and R2b audit): {matched}")

    if matched > 0:
        print(f"\nConfusion Matrix (MLGG leakage rules vs R2b LLM audit):")
        print(f"  TP={tp}, FP={fp}, FN={fn}, TN={tn}")
        sens = tp / (tp + fn) if (tp + fn) > 0 else 0
        spec = tn / (tn + fp) if (tn + fp) > 0 else 0
        ppv = tp / (tp + fp) if (tp + fp) > 0 else 0
        npv = tn / (tn + fn) if (tn + fn) > 0 else 0
        print(f"  Sensitivity: {sens:.3f}")
        print(f"  Specificity: {spec:.3f}")
        print(f"  PPV: {ppv:.3f}")
        print(f"  NPV: {npv:.3f}")

    # Per-rule analysis from the 172 scan
    print(f"\n{'='*70}")
    print("PER-RULE PREVALENCE (R1 scan, n=172)")
    print(f"{'='*70}")
    rule_prev = audit.get("rule_prevalence", {})
    print(f"{'Rule':<8} {'Repos':>6} {'Prev%':>6} {'Type':<10} {'Leakage?'}")
    for rule_id in sorted(rule_prev.keys()):
        data = rule_prev[rule_id]
        n = data.get("repos_affected", 0)
        pct = data.get("repo_prevalence_pct", 0)
        is_leak = rule_id in RULE_TO_LEAKAGE
        rtype = "LEAKAGE" if is_leak else "quality"
        print(f"{rule_id:<8} {n:>6} {pct:>5.1f}% {rtype:<10} "
              f"{'→ ' + ','.join(RULE_TO_LEAKAGE[rule_id]) if is_leak else ''}")

    # Leakage rule coverage
    leakage_rules = [r for r in rule_prev if r in RULE_TO_LEAKAGE]
    quality_rules = [r for r in rule_prev if r in QUALITY_RULES]

    leak_repos = set()
    for r in leakage_rules:
        leak_repos.update(range(rule_prev[r].get("repos_affected", 0)))

    print(f"\nLeakage rules fired on: {audit['scan_summary']['n_with_leakage']}/172 repos "
          f"({audit['scan_summary']['prevalence_pct']}%)")

    # Most common rule combinations
    print(f"\n{'='*70}")
    print("RULE CO-OCCURRENCE ANALYSIS")
    print(f"{'='*70}")

    # Check if per_repo has co-occurrence data
    if per_repo:
        combo_counter = Counter()
        for repo_id, rdata in per_repo.items():
            rules = frozenset(rdata.get("rules_fired", []))
            leak_rules = frozenset(r for r in rules if r in RULE_TO_LEAKAGE)
            if leak_rules:
                combo_counter[leak_rules] += 1

        print("Top leakage rule combinations:")
        for combo, count in combo_counter.most_common(10):
            print(f"  {count:>3}x: {', '.join(sorted(combo))}")
    else:
        print("  (per-repo data not available in audit file)")

    # Save results
    results = {
        "matched_papers": matched,
        "confusion_matrix": {"TP": tp, "FP": fp, "FN": fn, "TN": tn},
        "sensitivity": round(sens, 4) if matched > 0 else None,
        "specificity": round(spec, 4) if matched > 0 else None,
        "ppv": round(ppv, 4) if matched > 0 else None,
        "npv": round(npv, 4) if matched > 0 else None,
        "rule_prevalence_172": {
            r: {"repos": d.get("repos_affected", 0),
                "pct": d.get("repo_prevalence_pct", 0),
                "is_leakage_rule": r in RULE_TO_LEAKAGE}
            for r, d in rule_prev.items()
        },
    }

    out = OUTPUT_DIR / "e3_lint_accuracy.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
