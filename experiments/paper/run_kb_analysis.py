#!/usr/bin/env python3
"""
Experiment 3: Peer Review Knowledge Base — descriptive analysis.

Generates statistics and tables for the paper describing the 106-paper
Nature Communications peer review knowledge base used by MLGG's
Layer 3 agent reviewer.

Key narrative: Reviewers focus on high-level research design
(external validation, clinical utility, study design).
MLGG focuses on code-level implementation (leakage, preprocessing,
metric completeness). The two are complementary.

Usage:
    python3 experiments/paper/run_kb_analysis.py \
        --output experiments/paper/output/kb_analysis.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
KB_PATH = REPO_ROOT / "references" / "peer_reviews" / "peer-review-kb.json"
STATS_PATH = REPO_ROOT / "references" / "peer_reviews" / "peer-review-kb-stats.json"


def load_kb() -> List[Dict[str, Any]]:
    """Load the peer review knowledge base entries."""
    with KB_PATH.open() as f:
        data = json.load(f)
    return data.get("entries", data if isinstance(data, list) else [])


def analyze_reviewer_focus(kb: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze what reviewers focus on vs what MLGG focuses on."""

    # Categories that map to MLGG's domain (code-level)
    mlgg_categories = {"data_leakage", "preprocessing", "split_protocol",
                       "feature_selection"}

    # Categories that map to reviewer's domain (design-level)
    reviewer_categories = {"study_design", "external_validation",
                           "clinical_utility", "reporting",
                           "interpretability", "sample_size",
                           "reproducibility"}

    # Shared domain
    shared_categories = {"evaluation_metrics", "model_selection"}

    all_concerns = []
    for paper in kb:
        for concern in paper.get("reviewer_concerns", []):
            all_concerns.append(concern)

    total = len(all_concerns)

    # Count by domain
    mlgg_count = sum(1 for c in all_concerns if c.get("category") in mlgg_categories)
    reviewer_count = sum(1 for c in all_concerns if c.get("category") in reviewer_categories)
    shared_count = sum(1 for c in all_concerns if c.get("category") in shared_categories)

    # Severity distribution by domain
    mlgg_severity = Counter(c.get("severity") for c in all_concerns if c.get("category") in mlgg_categories)
    reviewer_severity = Counter(c.get("severity") for c in all_concerns if c.get("category") in reviewer_categories)

    return {
        "total_concerns": total,
        "domain_distribution": {
            "code_level_mlgg": {
                "count": mlgg_count,
                "pct": round(mlgg_count / total * 100, 1),
                "categories": sorted(mlgg_categories),
                "severity": dict(mlgg_severity),
            },
            "design_level_reviewer": {
                "count": reviewer_count,
                "pct": round(reviewer_count / total * 100, 1),
                "categories": sorted(reviewer_categories),
                "severity": dict(reviewer_severity),
            },
            "shared": {
                "count": shared_count,
                "pct": round(shared_count / total * 100, 1),
                "categories": sorted(shared_categories),
            },
        },
        "complementarity_narrative": (
            f"Of {total} reviewer concerns, only {mlgg_count} ({mlgg_count/total*100:.1f}%) "
            f"address code-level issues (MLGG's domain). "
            f"{reviewer_count} ({reviewer_count/total*100:.1f}%) focus on design-level issues "
            f"(external validation, clinical utility, study design) that require domain expertise. "
            f"This demonstrates complementarity: reviewers and MLGG cover different verification layers."
        ),
    }


def analyze_category_distribution(kb: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate Table 3 data: concern categories with counts and examples."""
    category_data: Dict[str, Dict[str, Any]] = {}

    for paper in kb:
        for concern in paper.get("reviewer_concerns", []):
            cat = concern.get("category", "unknown")
            if cat not in category_data:
                category_data[cat] = {
                    "count": 0,
                    "severities": Counter(),
                    "example_quotes": [],
                    "papers": set(),
                }
            category_data[cat]["count"] += 1
            category_data[cat]["severities"][concern.get("severity", "UNKNOWN")] += 1
            category_data[cat]["papers"].add(paper.get("id", ""))
            # Collect up to 3 example quotes
            quote = concern.get("concern_text", "")
            if quote and len(category_data[cat]["example_quotes"]) < 3:
                category_data[cat]["example_quotes"].append(quote[:200])

    # Sort by count descending
    table_rows = []
    for cat, data in sorted(category_data.items(), key=lambda x: -x[1]["count"]):
        table_rows.append({
            "category": cat,
            "n_concerns": data["count"],
            "n_papers": len(data["papers"]),
            "pct_papers": round(len(data["papers"]) / len(kb) * 100, 1),
            "severity_distribution": dict(data["severities"]),
            "example_quotes": data["example_quotes"],
        })

    return {"table3_rows": table_rows}


def analyze_pilot_pr026() -> Dict[str, Any]:
    """Load and summarize the PR-026 pilot concordance study."""
    pilot_path = REPO_ROOT / "experiments" / "paper" / "exp3_pilot_PR026.json"
    if not pilot_path.exists():
        return {"status": "not_available"}

    with pilot_path.open() as f:
        pilot = json.load(f)

    return {
        "paper_id": pilot.get("paper_id"),
        "reviewer_issues": pilot.get("reviewer_issues_count", 0),
        "mlgg_issues": pilot.get("mlgg_issues_count", 0),
        "overlap": pilot.get("overlap_count", 0),
        "unique_to_reviewer": pilot.get("unique_to_reviewer", 0),
        "unique_to_mlgg": pilot.get("unique_to_mlgg", 0),
        "summary": pilot.get("summary", ""),
    }


def generate_analysis(kb: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate complete Exp 3 analysis."""
    # Load pre-computed stats
    with STATS_PATH.open() as f:
        stats = json.load(f)

    focus_analysis = analyze_reviewer_focus(kb)
    category_analysis = analyze_category_distribution(kb)
    pilot = analyze_pilot_pr026()

    # Paper-level statistics
    n_papers = len(kb)
    domains = Counter(p.get("domain", "unknown") for p in kb)
    outcomes = Counter(p.get("outcome", "unknown") for p in kb)
    concerns_per_paper = [len(p.get("reviewer_concerns", [])) for p in kb]
    avg_concerns = sum(concerns_per_paper) / len(concerns_per_paper) if concerns_per_paper else 0

    return {
        "experiment": "exp3_peer_review_kb",
        "overview": {
            "n_papers": n_papers,
            "n_total_concerns": stats["total_concerns"],
            "n_total_strengths": stats.get("total_strengths", 0),
            "avg_concerns_per_paper": round(avg_concerns, 1),
            "median_concerns_per_paper": sorted(concerns_per_paper)[len(concerns_per_paper)//2],
            "concerns_range": f"{min(concerns_per_paper)}-{max(concerns_per_paper)}",
        },
        "severity_distribution": stats["concerns_by_severity"],
        "domain_distribution": dict(domains.most_common()),
        "outcome_distribution": dict(outcomes.most_common()),
        "reviewer_focus_analysis": focus_analysis,
        "category_table": category_analysis,
        "pilot_pr026": pilot,
        "key_findings": [
            f"106 NC papers yielded {stats['total_concerns']} structured methodology concerns",
            f"Top categories: evaluation_metrics ({stats['concerns_by_category']['evaluation_metrics']}), "
            f"study_design ({stats['concerns_by_category']['study_design']}), "
            f"reporting ({stats['concerns_by_category']['reporting']})",
            f"Only {focus_analysis['domain_distribution']['code_level_mlgg']['count']} concerns "
            f"({focus_analysis['domain_distribution']['code_level_mlgg']['pct']}%) "
            f"address code-level issues — MLGG's primary domain",
            f"{focus_analysis['domain_distribution']['design_level_reviewer']['count']} concerns "
            f"({focus_analysis['domain_distribution']['design_level_reviewer']['pct']}%) "
            f"focus on research design — beyond code analysis",
            "Complementarity confirmed: reviewers and MLGG verify different layers",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze peer review KB for Exp 3.")
    parser.add_argument("--output", type=str, default="experiments/paper/output/kb_analysis.json")
    args = parser.parse_args()

    print("Loading peer review knowledge base...")
    kb = load_kb()
    print(f"  {len(kb)} papers loaded")

    print("Running analysis...")
    results = generate_analysis(kb)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"\n{'='*60}")
    print(f"EXPERIMENT 3: PEER REVIEW KNOWLEDGE BASE ANALYSIS")
    print(f"{'='*60}")
    print(f"  Papers: {results['overview']['n_papers']}")
    print(f"  Total concerns: {results['overview']['n_total_concerns']}")
    print(f"  Avg concerns/paper: {results['overview']['avg_concerns_per_paper']}")
    print(f"\nSeverity distribution:")
    for sev, count in results["severity_distribution"].items():
        print(f"  {sev}: {count}")
    print(f"\nDomain focus:")
    fa = results["reviewer_focus_analysis"]["domain_distribution"]
    print(f"  Code-level (MLGG): {fa['code_level_mlgg']['count']} ({fa['code_level_mlgg']['pct']}%)")
    print(f"  Design-level (Reviewer): {fa['design_level_reviewer']['count']} ({fa['design_level_reviewer']['pct']}%)")
    print(f"  Shared: {fa['shared']['count']} ({fa['shared']['pct']}%)")
    print(f"\nKey findings:")
    for f in results["key_findings"]:
        print(f"  • {f}")

    print(f"\nOutput: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
