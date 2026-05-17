"""W9-D2: lint KB tag vocabulary against W6 style guide.

Warnings (WARN-only; doesn't fail CI on existing legacy):
  1. Tags matching narrowing patterns: *_for_*, *_in_*, *_when_*,
     *_during_*, *_across_*, *_with_*
  2. Tags appearing in <2 concerns (singletons - vocab drift)

Exit codes:
  0 - clean OR only existing-legacy warnings (with --baseline-mode)
  1 - new violations (only in strict mode without baseline)

Usage:
  lint_kb_tags.py                    # report all violations (WARN-only)
  lint_kb_tags.py --strict           # exit 1 on any violation
  lint_kb_tags.py --baseline-mode    # compare against committed baseline,
                                       only NEW violations fail

Companion to docs/KB_TAG_STYLE_GUIDE.md (W6 / commit ac33a19).
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
KB = REPO / "references/case-studies/peer-review-kb.json"
BASELINE_FILE = REPO / "references/case-studies/_tag_lint_baseline.json"

NARROWING_PATTERNS = [
    r"_for_", r"_in_", r"_when_", r"_during_", r"_across_", r"_with_",
]
NARROWING_RE = re.compile("|".join(NARROWING_PATTERNS))


def load_kb():
    return json.loads(KB.read_text())


def find_violations(data):
    """Returns dict: {singleton_tags: [...], narrowing_tags: [...], total: N}"""
    tag_freq = Counter()
    for entry in data.get("entries", []):
        for c in entry.get("reviewer_concerns", []):
            for t in c.get("tags", []):
                tag_freq[t] += 1
    singletons = sorted(t for t, n in tag_freq.items() if n < 2)
    narrowings = sorted(t for t in tag_freq if NARROWING_RE.search(t))
    return {
        "singletons": singletons,
        "narrowings": narrowings,
        "total_tags": len(tag_freq),
    }


def main():
    parser = argparse.ArgumentParser(prog="lint_kb_tags.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--strict", action="store_true",
                        help="Exit 1 on ANY violation (default: warn only)")
    parser.add_argument("--baseline-mode", action="store_true",
                        help="Exit 1 ONLY on violations NOT in committed baseline")
    args = parser.parse_args()

    data = load_kb()
    violations = find_violations(data)

    print("## KB tag lint (W9-D2)")
    print(f"Total unique tags: {violations['total_tags']}")
    print(f"Singletons (<2 uses): {len(violations['singletons'])}")
    print(f"Narrowing pattern (_for_/_in_/etc.): {len(violations['narrowings'])}")
    print()
    print("Top 5 narrowing examples:")
    for t in violations["narrowings"][:5]:
        print(f"  - {t}")

    if args.baseline_mode and BASELINE_FILE.exists():
        baseline = json.loads(BASELINE_FILE.read_text())
        new_singletons = set(violations["singletons"]) - set(baseline.get("singletons", []))
        new_narrowings = set(violations["narrowings"]) - set(baseline.get("narrowings", []))
        if new_singletons or new_narrowings:
            print(f"\nFAIL NEW violations: {len(new_singletons)} singletons, {len(new_narrowings)} narrowings")
            return 1
        print("\nOK No new violations vs baseline")
        return 0

    if args.strict and (violations["singletons"] or violations["narrowings"]):
        print(f"\nFAIL --strict mode: {len(violations['singletons'])} singleton + {len(violations['narrowings'])} narrowing violations")
        return 1

    print(f"\nWARN-only mode (no --strict): {len(violations['singletons'])} + {len(violations['narrowings'])} violations")
    print("    Use --strict on new tags OR --baseline-mode to enforce.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
