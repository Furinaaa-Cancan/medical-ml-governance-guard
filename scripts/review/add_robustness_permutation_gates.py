"""Additive backfill (2026-04-18) — give robustness_gate and
permutation_significance_gate the peer-review evidence they were missing.

These two gates had zero concerns in their mlgg_gates arrays even though
the KB contains tags the gates semantically own:

- `robustness_to_outliers`, `robustness_to_protocol`
  → robustness_gate (covers outlier sensitivity and protocol variation)

- `p_value_selection`, `p_value_error`, `statistical_significance_missing`
  → permutation_significance_gate (covers p-value abuse and missing
    null-distribution tests)

This script is additive only: it APPENDS the new gate to each affected
concern without removing or re-deriving existing mappings. That avoids
the regression mode of `backfill_peer_review_gates.py --force`, which
also drops previously-curated mappings the rule table doesn't replay.

Idempotent: re-running is a no-op (`_add_if_missing`).

Usage:
    python3 scripts/review/add_robustness_permutation_gates.py           # dry-run
    python3 scripts/review/add_robustness_permutation_gates.py --apply   # write
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KB_PATH = ROOT / "references" / "case-studies" / "peer-review-kb.json"

# Map: (tag substring matcher) → gate to append.
ADDITIONS: list[tuple[str, str]] = [
    ("robustness_to", "robustness_gate"),
    ("p_value_selection", "permutation_significance_gate"),
    ("p_value_error", "permutation_significance_gate"),
    ("statistical_significance_missing", "permutation_significance_gate"),
]


def _tag_matches(tags: list[str], needle: str) -> bool:
    return any(needle in str(t).lower() for t in tags)


def _add_if_missing(gates: list[str], gate: str) -> tuple[list[str], bool]:
    if gate in gates:
        return gates, False
    return gates + [gate], True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes to disk")
    args = parser.parse_args()

    kb = json.loads(KB_PATH.read_text())
    changed: list[tuple[str, str]] = []  # (concern_id, appended_gate)

    for entry in kb.get("entries", []):
        for concern in entry.get("reviewer_concerns", []):
            cid = concern.get("concern_id", "?")
            tags = concern.get("tags", [])
            current = list(concern.get("mlgg_gates", []))
            for needle, gate in ADDITIONS:
                if _tag_matches(tags, needle):
                    new, added = _add_if_missing(current, gate)
                    if added:
                        current = new
                        changed.append((cid, gate))
            concern["mlgg_gates"] = current

    print(f"Additions: {len(changed)}")
    for cid, gate in changed:
        print(f"  + {cid}  ← {gate}")

    if args.apply:
        KB_PATH.write_text(json.dumps(kb, indent=2, ensure_ascii=False) + "\n")
        print(f"\nWrote {KB_PATH}")
    else:
        print("\n(dry-run; pass --apply to write)")


if __name__ == "__main__":
    main()
