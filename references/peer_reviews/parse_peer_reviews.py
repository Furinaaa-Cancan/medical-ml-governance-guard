"""
parse_peer_reviews.py — Extract structured review data from NC peer review PDFs.

Extracts PDF text via pdftotext, then either:
  1. Outputs raw text for manual/LLM parsing (--extract-text)
  2. Merges per-paper JSONs into peer-review-kb.json (--merge)
  3. Generates stats from merged KB (--stats)

Per-paper JSONs are created manually or via LLM and placed in parsed/ directory.

Usage:
    python3 parse_peer_reviews.py --extract-text              # Extract all PDFs to text
    python3 parse_peer_reviews.py --extract-text --file X.pdf # Extract one PDF
    python3 parse_peer_reviews.py --merge                     # Merge parsed/ → kb.json
    python3 parse_peer_reviews.py --stats                     # Generate stats from kb
"""

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

REVIEWS_DIR = Path(__file__).resolve().parent / "nature_communications"
PARSED_DIR = REVIEWS_DIR / "parsed"
KB_PATH = REVIEWS_DIR.parent / "peer-review-kb.json"
STATS_PATH = REVIEWS_DIR.parent / "peer-review-kb-stats.json"
TAGS_PATH = REVIEWS_DIR.parent / "peer-review-kb-tags.json"


def extract_text(pdf_path: Path) -> str:
    """Extract text from PDF using pdftotext."""
    result = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout


def cmd_extract_text(args):
    """Extract PDF text for manual/LLM parsing."""
    out_dir = REVIEWS_DIR / "text"
    out_dir.mkdir(exist_ok=True)

    if args.file:
        pdfs = [REVIEWS_DIR / args.file]
    else:
        pdfs = sorted(REVIEWS_DIR.glob("*.pdf"))

    for pdf in pdfs:
        if not pdf.exists():
            print(f"[SKIP] {pdf.name} not found")
            continue
        text = extract_text(pdf)
        out_file = out_dir / pdf.with_suffix(".txt").name
        out_file.write_text(text, encoding="utf-8")
        lines = len(text.splitlines())
        print(f"[OK] {pdf.name} → {out_file.name} ({lines} lines)")

    print(f"\nExtracted to {out_dir}/")


def cmd_merge(args):
    """Merge all per-paper JSONs into peer-review-kb.json."""
    PARSED_DIR.mkdir(exist_ok=True)
    entries = []

    for jf in sorted(PARSED_DIR.glob("PR-*.json")):
        with open(jf) as f:
            entry = json.load(f)
        entries.append(entry)

    kb = {
        "contract_version": "peer_review_kb.v1",
        "total_papers": len(entries),
        "total_concerns": sum(len(e.get("reviewer_concerns", [])) for e in entries),
        "entries": entries,
    }

    KB_PATH.write_text(json.dumps(kb, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Merged {len(entries)} papers → {KB_PATH}")
    print(f"Total concerns: {kb['total_concerns']}")


def cmd_stats(args):
    """Generate statistics from the merged KB."""
    if not KB_PATH.exists():
        print("Run --merge first")
        sys.exit(1)

    with open(KB_PATH) as f:
        kb = json.load(f)

    entries = kb["entries"]
    all_concerns = []
    for e in entries:
        all_concerns.extend(e.get("reviewer_concerns", []))

    # Category counts
    cat_counter = Counter(c.get("category", "unknown") for c in all_concerns)

    # Severity counts
    sev_counter = Counter(c.get("severity", "unknown") for c in all_concerns)

    # Dimension counts
    dim_counter = Counter(c.get("mlgg_dimension", 0) for c in all_concerns)

    # Tag counts
    tag_counter = Counter()
    for c in all_concerns:
        for tag in c.get("tags", []):
            tag_counter[tag] += 1

    # Resolution rate
    resolved = sum(1 for c in all_concerns if c.get("resolved"))
    resolution_rate = resolved / len(all_concerns) if all_concerns else 0

    # Domain distribution
    domain_counter = Counter(e.get("domain", "unknown") for e in entries)

    # Outcome distribution
    outcome_counter = Counter(e.get("outcome", "unknown") for e in entries)

    stats = {
        "total_papers": len(entries),
        "total_concerns": len(all_concerns),
        "total_strengths": sum(len(e.get("reviewer_strengths", [])) for e in entries),
        "concerns_by_category": dict(cat_counter.most_common()),
        "concerns_by_severity": dict(sev_counter.most_common()),
        "concerns_by_dimension": {str(k): v for k, v in sorted(dim_counter.items())},
        "top_30_tags": [{"tag": t, "count": n} for t, n in tag_counter.most_common(30)],
        "resolution_rate": round(resolution_rate, 3),
        "papers_by_domain": dict(domain_counter.most_common()),
        "papers_by_outcome": dict(outcome_counter.most_common()),
    }

    STATS_PATH.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Stats → {STATS_PATH}")
    print(json.dumps(stats, indent=2))

    # Tag index
    tag_index = defaultdict(list)
    for c in all_concerns:
        for tag in c.get("tags", []):
            tag_index[tag].append(c.get("concern_id", ""))

    TAGS_PATH.write_text(
        json.dumps(dict(sorted(tag_index.items())), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nTag index → {TAGS_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Parse NC peer review PDFs")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--extract-text", action="store_true", help="Extract PDF text")
    group.add_argument("--merge", action="store_true", help="Merge parsed JSONs → KB")
    group.add_argument("--stats", action="store_true", help="Generate stats from KB")
    parser.add_argument("--file", type=str, help="Single PDF filename (with --extract-text)")
    args = parser.parse_args()

    if args.extract_text:
        cmd_extract_text(args)
    elif args.merge:
        cmd_merge(args)
    elif args.stats:
        cmd_stats(args)


if __name__ == "__main__":
    main()
