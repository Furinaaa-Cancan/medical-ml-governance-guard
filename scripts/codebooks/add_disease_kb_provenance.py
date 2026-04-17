"""P0-2 migration: add `provenance` metadata to each disease entry in
references/methodology/disease-definition-knowledge-base.json.

Problem: Memory note project_disease_kb_provenance.md records that the
per-disease variable lists (definition_variables_to_exclude, lab_criteria,
medications) were LLM-compiled and have not been clinician-reviewed, yet
cohort_definition_gate + codebook RAG treat them as ground truth.

Fix: Annotate each disease with explicit provenance so downstream consumers
can surface the trust level to users; add a DISEASE_KB_REVIEW.md checklist
for clinical collaborators to certify entries one by one.

Idempotent: re-running is a no-op for already-annotated entries unless --force.

Usage:
    python3 scripts/codebooks/add_disease_kb_provenance.py           # dry-run
    python3 scripts/codebooks/add_disease_kb_provenance.py --apply   # write
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KB_PATH = ROOT / "references" / "methodology" / "disease-definition-knowledge-base.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _kb_provenance import REVIEW_STATUS_PENDING  # noqa: E402

DEFAULT_PROVENANCE = {
    "source": "llm_compiled",
    "description": (
        "ICD/medication/lab lists compiled by LLM against the Torralbo 2025 + "
        "Eastwood 2016 methodology references in the top-level "
        "methodology_reference block. The overall structure (5 evidence layers, "
        "multi-source adjudication) follows established literature; the specific "
        "per-disease variable enumerations have NOT been individually verified "
        "by a clinician for this KB version."
    ),
    "clinician_review_status": REVIEW_STATUS_PENDING,
    "last_reviewed": None,
    "reviewer": None,
    "review_checklist": "references/methodology/DISEASE_KB_REVIEW.md",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing provenance blocks (reset to pending)",
    )
    args = parser.parse_args()

    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    diseases = kb.get("diseases", {})
    added = 0
    skipped = 0
    for name, entry in diseases.items():
        if "provenance" in entry and not args.force:
            skipped += 1
            continue
        entry["provenance"] = dict(DEFAULT_PROVENANCE)
        added += 1

    # Also update top-level description to reference the per-entry provenance
    if added > 0 or args.force:
        kb["version"] = "1.1"
        kb.setdefault("change_log", []).append(
            {
                "version": "1.1",
                "date": "2026-04-17",
                "change": (
                    "P0-2: added per-disease provenance field. All 11 entries "
                    "initialized as llm_compiled / clinician_review_status=pending. "
                    "Downstream consumers (cohort_definition_gate, codebook task_aware_validate) "
                    "surface provenance to the user for manual arbitration."
                ),
            }
        )

    print(f"Added provenance to: {added} diseases")
    print(f"Skipped (already have provenance): {skipped}")

    if not args.apply:
        print("(dry-run; pass --apply to write)")
        return

    KB_PATH.write_text(json.dumps(kb, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {KB_PATH}")


if __name__ == "__main__":
    main()
