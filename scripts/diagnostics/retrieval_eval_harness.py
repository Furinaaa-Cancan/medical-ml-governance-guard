#!/usr/bin/env python3
"""
End-to-end evaluation harness for peer-review-kb retrieval.

Consumes a scenarios file (see references/retrieval_eval/scenarios.json)
where each scenario declares:

    gate_name          — the gate that would have failed
    failure_codes[]    — issue codes surfaced by that gate
    expected_categories[] — categories the reviewer would expect to see
    expected_tags[]    — tags the reviewer would expect to see

For each scenario it runs the same ``retrieve_for_failure`` call the
gate framework's peer-review-context hook uses and scores the top-K
(default 5) results against the expectations:

    coverage = 1 if ANY of top-K concerns' category ∈ expected_categories
    precision = |top-K tags ∩ expected_tags| / |expected_tags|
    hit@K   = 1 if ANY top-K concern has ≥1 expected tag

This is NOT a unit test of retrieval internals — those live in
tests/test_peer_review_retrieval*.py. This answers the harder
question: "does the retrieval actually surface what a reviewer
would expect when a gate fails?"

Run:
    python3 scripts/diagnostics/retrieval_eval_harness.py \
        --scenarios references/retrieval_eval/scenarios.json \
        --report /tmp/retrieval_eval_report.json \
        --baseline references/retrieval_eval/baseline.json \
        --strict

Strict mode fails (exit 2) if any scenario regresses below its baseline
coverage / hit@K / precision. Without --baseline the harness only
prints current numbers, which is useful for a first run.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core")
if _CORE_DIR not in _sys.path:
    _sys.path.insert(0, _CORE_DIR)

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from _peer_review_retrieval import retrieve_for_failure


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SCENARIOS = REPO_ROOT / "references" / "retrieval_eval" / "scenarios.json"
DEFAULT_KB = REPO_ROOT / "references" / "case-studies" / "peer-review-kb.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    p.add_argument("--kb", type=Path, default=DEFAULT_KB,
                   help="Override KB path (mainly for tests).")
    p.add_argument("--report", type=Path,
                   help="Optional JSON report output path")
    p.add_argument("--baseline", type=Path,
                   help="Optional baseline JSON; --strict regresses against it")
    p.add_argument("--top-k", type=int, default=5,
                   help="Top-K to retrieve per scenario (default 5)")
    p.add_argument("--strict", action="store_true",
                   help="Exit 2 if any scenario regresses or misses hit@K")
    p.add_argument("--verbose", action="store_true",
                   help="Print per-scenario top-K details")
    return p.parse_args()


def evaluate_scenario(
    scenario: Dict[str, Any],
    *,
    kb_path: Path,
    top_k: int,
) -> Dict[str, Any]:
    gate = scenario["gate_name"]
    codes = scenario.get("failure_codes", [])
    expected_cats = set(scenario.get("expected_categories", []))
    expected_tags = set(scenario.get("expected_tags", []))

    results = retrieve_for_failure(gate, codes, limit=top_k, kb_path=kb_path)

    hit_categories: List[str] = []
    hit_tags: List[str] = []
    retrieved_summary: List[Dict[str, Any]] = []

    for r in results:
        cat = r.get("category")
        tags = [t for t in r.get("tags", []) if isinstance(t, str)]
        if cat in expected_cats:
            hit_categories.append(cat)
        for t in tags:
            if t in expected_tags:
                hit_tags.append(t)
        retrieved_summary.append({
            "concern_id": r.get("concern_id"),
            "paper_id": r.get("_paper_id") or r.get("paper_id"),
            "severity": r.get("severity"),
            "category": cat,
            "tags": tags,
            "retrieval_mode": r.get("_retrieval_mode"),
        })

    coverage = 1.0 if hit_categories else 0.0
    hit_at_k = 1.0 if hit_tags else 0.0
    # Precision = fraction of expected tags that appeared in top-K.
    # Compute against unique expected tags (not total occurrences) so
    # the number is bounded in [0,1] and easy to interpret.
    unique_hits = set(hit_tags) & expected_tags
    tag_precision = (
        len(unique_hits) / len(expected_tags) if expected_tags else 0.0
    )

    return {
        "scenario_id": scenario["scenario_id"],
        "description": scenario.get("description", ""),
        "gate_name": gate,
        "retrieved_count": len(results),
        "coverage": coverage,
        "hit_at_k": hit_at_k,
        "tag_precision": round(tag_precision, 3),
        "matched_expected_categories": sorted(set(hit_categories)),
        "matched_expected_tags": sorted(unique_hits),
        "top_k_summary": retrieved_summary,
    }


def print_human_summary(
    report: Dict[str, Any], *, verbose: bool = False,
) -> None:
    print("=" * 70)
    print("Retrieval eval harness — peer-review-kb")
    print("=" * 70)
    for r in report["scenarios"]:
        mark_cov = "OK" if r["coverage"] >= 1.0 else "MISS"
        mark_hit = "OK" if r["hit_at_k"] >= 1.0 else "MISS"
        print(f"\n  [{r['scenario_id']}] gate={r['gate_name']}")
        print(f"    retrieved: {r['retrieved_count']}  "
              f"coverage(category): {r['coverage']:.0f} [{mark_cov}]  "
              f"hit@K(tag): {r['hit_at_k']:.0f} [{mark_hit}]  "
              f"tag_precision: {r['tag_precision']:.3f}")
        if r["matched_expected_categories"]:
            print(f"    matched category : {r['matched_expected_categories']}")
        if r["matched_expected_tags"]:
            print(f"    matched tags     : {r['matched_expected_tags']}")
        if verbose:
            for i, c in enumerate(r["top_k_summary"], 1):
                print(f"      {i}. {c['concern_id']} ({c['paper_id']}, "
                      f"{c['severity']}) [{c['category']}] "
                      f"mode={c['retrieval_mode']}")
                print(f"         tags: {c['tags'][:6]}")
    agg = report["aggregate"]
    print("\n" + "-" * 70)
    print(f"  Aggregate: coverage={agg['coverage_rate']:.2f} "
          f"hit@K={agg['hit_at_k_rate']:.2f} "
          f"mean_tag_precision={agg['mean_tag_precision']:.3f} "
          f"scenarios={agg['total_scenarios']}")
    print("=" * 70)


def check_regression(
    current: Dict[str, Any],
    baseline: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return a list of regression entries. Empty list = no regression."""
    regressions: List[Dict[str, Any]] = []
    baseline_by_id = {s["scenario_id"]: s for s in baseline["scenarios"]}
    for s in current["scenarios"]:
        b = baseline_by_id.get(s["scenario_id"])
        if b is None:
            # New scenario → no baseline to regress against, skip.
            continue
        if s["coverage"] < b["coverage"]:
            regressions.append({
                "scenario_id": s["scenario_id"],
                "metric": "coverage",
                "baseline": b["coverage"],
                "current": s["coverage"],
            })
        if s["hit_at_k"] < b["hit_at_k"]:
            regressions.append({
                "scenario_id": s["scenario_id"],
                "metric": "hit_at_k",
                "baseline": b["hit_at_k"],
                "current": s["hit_at_k"],
            })
        # Allow tag_precision to move slightly (floor at baseline − 0.05)
        # to avoid noise from minor KB rewording that shifts token matches.
        if s["tag_precision"] < b["tag_precision"] - 0.05:
            regressions.append({
                "scenario_id": s["scenario_id"],
                "metric": "tag_precision",
                "baseline": b["tag_precision"],
                "current": s["tag_precision"],
            })
    return regressions


def main() -> int:
    args = parse_args()

    scenarios_path = Path(args.scenarios).expanduser().resolve()
    if not scenarios_path.exists():
        print(f"ERROR: scenarios file not found: {scenarios_path}",
              file=_sys.stderr)
        return 2
    with scenarios_path.open("r", encoding="utf-8") as fh:
        scenarios_data = json.load(fh)
    scenarios = scenarios_data.get("scenarios", [])
    if not scenarios:
        print("ERROR: scenarios list is empty", file=_sys.stderr)
        return 2

    kb_path = Path(args.kb).expanduser().resolve()

    per_scenario = [
        evaluate_scenario(s, kb_path=kb_path, top_k=args.top_k)
        for s in scenarios
    ]
    total = len(per_scenario)
    coverage_rate = sum(s["coverage"] for s in per_scenario) / total
    hit_rate = sum(s["hit_at_k"] for s in per_scenario) / total
    mean_precision = (
        sum(s["tag_precision"] for s in per_scenario) / total
    )
    report = {
        "scenarios_file": str(scenarios_path),
        "kb_path": str(kb_path),
        "top_k": args.top_k,
        "scenarios": per_scenario,
        "aggregate": {
            "total_scenarios": total,
            "coverage_rate": round(coverage_rate, 3),
            "hit_at_k_rate": round(hit_rate, 3),
            "mean_tag_precision": round(mean_precision, 3),
        },
    }

    print_human_summary(report, verbose=args.verbose)

    # Optional: persist.
    if args.report:
        out = Path(args.report).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    # Optional: regression check against baseline.
    regressions: List[Dict[str, Any]] = []
    if args.baseline:
        baseline_path = Path(args.baseline).expanduser().resolve()
        if baseline_path.exists():
            try:
                baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
                regressions = check_regression(report, baseline)
                if regressions:
                    print("\nREGRESSIONS vs baseline:")
                    for r in regressions:
                        print(f"  [{r['scenario_id']}] {r['metric']}: "
                              f"{r['baseline']} → {r['current']}")
            except Exception as exc:
                print(f"ERROR: baseline unreadable: {exc}",
                      file=_sys.stderr)
                return 2
        else:
            print(f"\nBASELINE: {baseline_path} missing — nothing to compare.")

    if args.strict:
        # Fail-closed conditions: any regression, or any scenario missing
        # hit@K entirely (if baseline didn't exist, we still enforce the
        # minimum "at least 1 top-K concern matched an expected tag").
        if regressions:
            return 2
        for s in per_scenario:
            if s["hit_at_k"] < 1.0:
                print(f"\nSTRICT FAIL: scenario '{s['scenario_id']}' has "
                      f"hit@K=0 — top-{args.top_k} concerns matched no "
                      f"expected tag.", file=_sys.stderr)
                return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
