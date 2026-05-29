"""CLI for querying the Peer Review Knowledge Base.

Usage:
    python3 scripts/review/peer_review_lookup.py --dimension 5 --severity HIGH
    python3 scripts/review/peer_review_lookup.py --gate leakage_gate
    python3 scripts/review/peer_review_lookup.py --tags "missing_calibration,no_dca"
    python3 scripts/review/peer_review_lookup.py --category evaluation_metrics --limit 3
    python3 scripts/review/peer_review_lookup.py --domain oncology
    python3 scripts/review/peer_review_lookup.py --stats
"""

import argparse
import sys
from pathlib import Path as _Path

# Ensure the repo root is on sys.path so ``scripts.rag.*`` imports work when
# this file is invoked directly via ``python3 scripts/review/peer_review_lookup.py``.
_REPO_ROOT = _Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.rag.retrieval.bm25 import (  # noqa: E402
    format_peer_context,
    get_stats_summary,
    retrieve_by_category,
    retrieve_by_dimension,
    retrieve_by_domain,
    retrieve_by_gate,
    retrieve_by_tags,
    retrieve_by_text,
    retrieve_for_failure,
)

DIMENSION_NAMES = {
    1: "Data Integrity",
    2: "Leakage Prevention",
    3: "Pipeline Isolation",
    4: "Model Selection Rigor",
    5: "Statistical Validity",
    6: "Generalization Evidence",
    7: "Clinical Completeness",
    8: "Reporting Standards",
    9: "Reproducibility",
    10: "Security & Provenance",
    11: "Fairness & Equity",
    12: "Sample Size Adequacy",
}


def cmd_stats():
    """Display overall KB statistics."""
    stats = get_stats_summary()
    print("╔══════════════════════════════════════════════════╗")
    print("║     Peer Review Knowledge Base — Statistics      ║")
    print("╚══════════════════════════════════════════════════╝")
    print(f"\n  Papers:   {stats['total_papers']}")
    print(f"  Concerns: {stats['total_concerns']}")
    print(f"  Strengths: {stats['total_strengths']}")

    print("\n  Concerns by Category:")
    for cat, n in stats.get("concerns_by_category", {}).items():
        pct = n / stats["total_concerns"] * 100
        bar = "█" * int(pct / 2)
        print(f"    {cat:<25} {n:>4}  {bar} ({pct:.1f}%)")

    print("\n  Concerns by Severity:")
    for sev, n in stats.get("concerns_by_severity", {}).items():
        print(f"    {sev:<10} {n:>4}")

    print("\n  Top Tags:")
    for entry in stats.get("top_30_tags", [])[:10]:
        print(f"    {entry['tag']:<40} {entry['count']:>3}")

    print(f"\n  Resolution Rate: {stats.get('resolution_rate', 0):.1%}")


def cmd_query(args):
    """Run a query and display results."""
    results = []
    title = ""

    if args.dimension is not None:
        dim_name = DIMENSION_NAMES.get(args.dimension, "?")
        title = f"Dimension {args.dimension}: {dim_name}"
        results = retrieve_by_dimension(args.dimension, severity=args.severity, limit=args.limit)

    elif args.gate:
        if args.issue_codes:
            codes = [c.strip() for c in args.issue_codes.split(",") if c.strip()]
            title = f"Gate: {args.gate} (re-ranked by issue codes: {', '.join(codes)})"
            # retrieve_for_failure does not accept a severity filter — it
            # ranks by issue-code relevance, falling back to severity only
            # when keyword score is zero. Severity filter would fight the
            # keyword signal. Warn the user if both were passed.
            if args.severity:
                print(
                    "  Note: --severity ignored when --issue-codes is given "
                    "(ranking already severity-aware on tie).\n",
                    file=sys.stderr,
                )
            results = retrieve_for_failure(args.gate, codes, limit=args.limit)
        else:
            title = f"Gate: {args.gate}"
            results = retrieve_by_gate(args.gate, severity=args.severity, limit=args.limit)

    elif args.tags:
        tag_list = [t.strip() for t in args.tags.split(",")]
        title = f"Tags: {', '.join(tag_list)}"
        results = retrieve_by_tags(tag_list, severity=args.severity, limit=args.limit)

    elif args.category:
        title = f"Category: {args.category}"
        results = retrieve_by_category(args.category, severity=args.severity, limit=args.limit)

    elif args.domain:
        title = f"Domain: {args.domain}"
        results = retrieve_by_domain(args.domain, severity=args.severity, limit=args.limit)

    elif args.search:
        title = f"Text search: '{args.search}'"
        results = retrieve_by_text(args.search, severity=args.severity, limit=args.limit)

    print(f"\n  Query: {title}")
    if args.severity:
        print(f"  Filter: severity={args.severity}")
    print(f"  Results: {len(results)}\n")
    print(format_peer_context(results, max_display=args.limit))


def main():
    parser = argparse.ArgumentParser(description="Query Peer Review Knowledge Base")
    parser.add_argument("--stats", action="store_true", help="Show KB statistics")
    parser.add_argument("--dimension", type=int, help="MLGG dimension (1-12)")
    parser.add_argument("--gate", type=str, help="Gate name (e.g., leakage_gate)")
    parser.add_argument(
        "--issue-codes",
        type=str,
        help=(
            "Comma-separated failure codes (e.g., 'clinical_floor_ppv_not_met,"
            "baseline_improvement_insufficient'). Only used with --gate. "
            "Re-ranks candidates by issue-code keyword overlap so output "
            "matches the JSON envelope's peer_review_context."
        ),
    )
    parser.add_argument("--tags", type=str, help="Comma-separated tags")
    parser.add_argument("--category", type=str, help="Concern category")
    parser.add_argument("--domain", type=str, help="Clinical domain")
    parser.add_argument("--search", type=str, help="Free-text search in concern text")
    parser.add_argument("--severity", type=str, help="Filter by severity")
    parser.add_argument("--limit", type=int, default=5, help="Max results (default: 5)")
    args = parser.parse_args()

    if args.stats:
        cmd_stats()
    elif any([args.dimension is not None, args.gate, args.tags, args.category, args.domain, args.search]):
        cmd_query(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
