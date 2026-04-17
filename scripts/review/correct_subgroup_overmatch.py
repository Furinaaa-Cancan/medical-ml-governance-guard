"""One-shot correction for the subgroup→fairness over-match bug surfaced
by the 2026-04-17 Codex review of P0-3b.

The original `subgroup` substring rule fired on ANY tag containing
"subgroup" (including "subgroup_stratification" for confounder adjustment,
"subgroup_by_treatment" for clinical heterogeneity, "small_subgroup_
overclaimed" for sample-size issues, etc.). 5 concerns were incorrectly
assigned `fairness_equity_gate`. This script removes that gate from the
affected concerns and re-derives the correct mapping from the updated
rule table in backfill_peer_review_gates.py.

Idempotent. Safe to re-run.

Usage:
    python3 scripts/review/correct_subgroup_overmatch.py           # dry-run
    python3 scripts/review/correct_subgroup_overmatch.py --apply   # write
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KB_PATH = ROOT / "references" / "case-studies" / "peer-review-kb.json"

# Known affected concern IDs — the 5 identified by the Codex review.
# PR-078-C03 is included: it had `gender_bias` (legitimately fairness)
# but was ALSO matched via the over-broad `subgroup` rule; the corrected
# rule table now hits it via `gender_bias` directly, so fairness_equity_gate
# is still correct for PR-078-C03 but assigned for the right reason.
AFFECTED_IDS = {
    "PR-005-C04",  # treatment heterogeneity — not fairness
    "PR-034-C02",  # confounder stratification — not fairness
    "PR-051-C03",  # small subgroup underpowered — sample size
    "PR-062-C03",  # selective reporting — reporting bias
    "PR-078-C03",  # gender bias — IS fairness, but via gender_bias tag now
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    # Import the updated rule engine so corrections follow the current rules.
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts" / "review"))
    from backfill_peer_review_gates import _derive_gates  # type: ignore

    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    changes: list[tuple[str, list[str], list[str]]] = []

    for entry in kb["entries"]:
        for c in entry.get("reviewer_concerns", []):
            cid = c["concern_id"]
            if cid not in AFFECTED_IDS:
                continue
            before = list(c.get("mlgg_gates") or [])
            # Re-derive from current rule table (subgroup rule is now removed;
            # fairness only fires on narrow signals like gender_bias).
            rederived = _derive_gates(c["category"], c.get("tags") or [])
            if not rederived:
                rederived = ["publication_gate"]
            # Replace (not union) so the wrong fairness_equity_gate is purged.
            after = list(dict.fromkeys(rederived))
            if after != before:
                c["mlgg_gates"] = after
                changes.append((cid, before, after))

    print(f"Concerns corrected: {len(changes)}")
    for cid, before, after in changes:
        print(f"  {cid}: {before} -> {after}")

    if not args.apply:
        print("\n(dry-run; pass --apply to write)")
        return

    if not changes:
        print("\nNothing to write.")
        return

    kb.setdefault("change_log", []).append(
        {
            "version": "v1.3",
            "date": "2026-04-17",
            "change": (
                "Codex-review fix: removed fairness_equity_gate from "
                f"{len(changes)} concerns where it was assigned via the "
                "over-broad 'subgroup' substring rule. Narrower fairness "
                "rules (subgroup_disparity / subgroup_fairness / "
                "gender_bias / racial_bias / ethnic_bias) now gate this."
            ),
        }
    )
    kb["contract_version"] = "peer_review_kb.v1.3"

    tmp_path = KB_PATH.with_suffix(KB_PATH.suffix + ".tmp")
    tmp_path.write_text(json.dumps(kb, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp_path, KB_PATH)
    print(f"\nWrote {KB_PATH}")


if __name__ == "__main__":
    main()
