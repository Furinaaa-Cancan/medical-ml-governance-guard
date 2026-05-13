#!/usr/bin/env python3
"""Merge discovered+downloaded PDFs into peer-review-kb.json as new entries.

Reads:
  paper/discovery-candidates.json (614 candidates)
  references/case-studies/{nc,cm,npj_dm}/<doi>_peer_review.pdf (downloaded subset)

For each candidate where the corresponding PDF exists on disk:
  Add a new KB entry with:
    - id: PR-EXP-NNNN (sequentially numbered, starts at PR-EXP-0001)
    - paper_doi (factual identifier)
    - paper_title (factual identifier)
    - journal, year (factual)
    - peer_review_pdf_path (verified)
    - openalex_id (provenance)
    - matched_query (provenance: which OpenAlex search hit it)
    - is_oa, cited_by_count (factual metadata)
    - data_type: "pending_metadata_extraction"
    - prediction_task: "pending_metadata_extraction"
    - reviewer_concerns: [] (intentionally empty; no fabrication)
    - _validation_status: explicit "metadata-only entry, no concerns extracted"
    - metadata_source: "openalex_discovery_2026-05"

Does NOT touch the existing 118 manually-curated entries.

Writes:
  - peer-review-kb.json (mutated)
  - paper/kb-merge-report.md (summary of additions)
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KB = ROOT / "references" / "case-studies" / "peer-review-kb.json"
CAND = ROOT / "paper" / "discovery-candidates.json"
REPORT = ROOT / "paper" / "kb-merge-report.md"

JOURNAL_DIRS = {
    "Nature Communications":   ROOT / "references" / "case-studies" / "nature_communications",
    "npj Digital Medicine":    ROOT / "references" / "case-studies" / "npj_digital_medicine",
    "Communications Medicine": ROOT / "references" / "case-studies" / "communications_medicine",
}

def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    kb = json.loads(KB.read_text())
    candidates = json.loads(CAND.read_text())["candidates"]
    ts = datetime.now(timezone.utc).isoformat()

    # Map existing entries DOI → entry to skip dupes
    existing_dois = {e['paper_doi'].lower() for e in kb['entries']}

    # Find next PR-EXP-NNNN id
    existing_exp = [e['id'] for e in kb['entries'] if e['id'].startswith('PR-EXP-')]
    next_n = max((int(eid.split('-')[-1]) for eid in existing_exp), default=0) + 1

    added = 0
    skipped_dup = 0
    skipped_no_pdf = 0
    new_entries = []

    for c in candidates:
        doi = c['doi'].lower()
        if doi in existing_dois:
            skipped_dup += 1
            continue
        # Locate PDF
        target_dir = JOURNAL_DIRS.get(c['journal'])
        if not target_dir:
            skipped_no_pdf += 1
            continue
        doi_short = doi.replace("10.1038/", "")
        pdf_path = target_dir / f"{doi_short}_peer_review.pdf"
        if not pdf_path.exists() or pdf_path.stat().st_size < 10000:
            skipped_no_pdf += 1
            continue
        # Verify it's a real PDF
        with open(pdf_path, 'rb') as f:
            head = f.read(8)
        if not head.startswith(b'%PDF-'):
            skipped_no_pdf += 1
            continue

        new_id = f"PR-EXP-{next_n:04d}"
        next_n += 1
        new_entry = {
            "id": new_id,
            "paper_doi": c['doi'],  # original case
            "paper_title": c['title'],
            "journal": c['journal'],
            "year": c['year'],
            "peer_review_pdf_path": str(pdf_path.relative_to(ROOT)),
            "pdf_verification": {
                "method": "filename_doi_match",
                "confidence": "high",
                "note": "Filename matches OpenAlex-discovered DOI; PDF magic bytes verified.",
                "verified_at": ts,
            },
            "metadata_source": "openalex_discovery_2026-05",
            "data_type": "pending_metadata_extraction",
            "prediction_task": "pending_metadata_extraction",
            "reviewer_concerns": [],
            "_validation_status": (
                "Metadata-only entry from automated OpenAlex discovery. "
                "data_type, prediction_task, and reviewer_concerns NOT extracted. "
                "Do not include in concern-based or scope-filtered analyses until manually validated."
            ),
            "_field_provenance": {
                "discovery": {
                    "source": "openalex",
                    "openalex_id": c.get('openalex_id'),
                    "matched_query": c.get('matched_query'),
                    "is_oa": c.get('is_oa'),
                    "cited_by_count": c.get('cited_by_count'),
                    "discovered_at_utc": ts,
                },
            },
        }
        new_entries.append(new_entry)
        existing_dois.add(doi)
        added += 1

    # Append all new entries
    kb['entries'].extend(new_entries)
    kb['total_papers'] = len(kb['entries'])
    kb['total_concerns'] = sum(len(e.get('reviewer_concerns', [])) for e in kb['entries'])

    # Audit record
    kb.setdefault('provenance', {}).setdefault('integrity_audits', []).append({
        'audited_at_utc': ts,
        'method': 'OpenAlex discovery + selective TPR-PDF download + bare-metadata KB merge',
        'result': {
            'added_entries': added,
            'skipped_duplicate_doi': skipped_dup,
            'skipped_no_pdf_or_invalid': skipped_no_pdf,
            'new_id_range': (
                f"PR-EXP-{next_n - added:04d} to PR-EXP-{next_n - 1:04d}"
                if added else 'none'
            ),
            'note': (
                "New entries are metadata-only (DOI/title/journal/year/PDF path). "
                "data_type, prediction_task, reviewer_concerns are intentionally empty "
                "to avoid fabrication. Manual extraction or trusted automated extraction "
                "with annotator validation must precede paper-grade use."
            ),
        },
    })

    KB.write_text(json.dumps(kb, indent=2, ensure_ascii=False))

    # Stats by journal
    from collections import Counter
    by_journal = Counter(e['journal'] for e in new_entries)

    md = [
        f"# KB merge report — {ts}",
        "",
        "## Summary",
        "",
        f"- Candidates considered: {len(candidates)}",
        f"- Skipped (DOI already in KB): {skipped_dup}",
        f"- Skipped (no PDF on disk or invalid): {skipped_no_pdf}",
        f"- **Added: {added}** entries with verified PDF",
        "",
        "## By journal",
        "",
    ]
    for j, n in by_journal.most_common():
        md.append(f"- {j}: {n}")
    md.append("")
    md.append("## After merge")
    md.append(f"- KB total entries: {kb['total_papers']}")
    md.append(f"- KB total concerns: {kb['total_concerns']}")
    md.append("")
    md.append("## Caveats")
    md.append(f"- All {added} new entries have `data_type='pending_metadata_extraction'`,")
    md.append("  `prediction_task='pending_metadata_extraction'`, and `reviewer_concerns=[]`.")
    md.append("- They MUST NOT be used for scope-filtering or concern-based claims until validated.")
    md.append("- Use them only for: PDF text mining, mlgg-lint audit on linked code, ")
    md.append("  prevalence statistics over a clearly-marked discovery subset.")
    REPORT.write_text("\n".join(md))

    print(f"Added: {added} new entries")
    print(f"Skipped (duplicate): {skipped_dup}")
    print(f"Skipped (no/invalid PDF): {skipped_no_pdf}")
    print("")
    print("By journal:")
    for j, n in by_journal.most_common():
        print(f"  {j}: {n}")
    print("")
    print(f"KB total: {kb['total_papers']} entries (was 118 before merge)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
