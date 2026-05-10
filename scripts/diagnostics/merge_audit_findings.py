#!/usr/bin/env python3
"""Merge 5-agent audit findings into peer-review-kb.json.

Reads:
  /tmp/audit-chunk-{1,2,3,4,5}-output.json (217 entries' structured audit)

For each PR-EXP entry:
  - Apply data_type (replace pending_metadata_extraction)
  - Apply prediction_task (replace pending_metadata_extraction)
  - Add is_cohort_retrospective_binary flag (mlgg strict scope filter)
  - Add audit_findings sub-dict: confidence, anomaly_flags, evidence_basis, sample_size
  - For corrupt PDFs: mark _validation_status = "pdf_corrupt_needs_redownload"
  - For not-medical-ml: mark out_of_scope_reason = "not_medical_ml"

Writes mutated KB. Adds provenance entry.

Output: /tmp/merge-audit-summary.json with stats
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent.parent
KB_PATH = ROOT / "references" / "case-studies" / "peer-review-kb.json"
ts = datetime.now(timezone.utc).isoformat()

# Load 5 chunk outputs
audit = {}
for n in range(1, 6):
    chunk = json.loads(Path(f"/tmp/audit-chunk-{n}-output.json").read_text())
    for rec in chunk:
        audit[rec["id"]] = rec
print(f"Loaded {len(audit)} audit records from 5 chunks")

# Load KB
kb = json.loads(KB_PATH.read_text())

stats = Counter()
applied = 0
corrupt = []
out_of_scope = []
non_cohort = []

for e in kb["entries"]:
    eid = e["id"]
    if eid not in audit:
        continue
    a = audit[eid]

    # Apply structured extraction
    if a.get("data_type") and a["data_type"] != "pending_metadata_extraction":
        e["data_type"] = a["data_type"]
        stats["data_type_filled"] += 1
    if a.get("prediction_task") and a["prediction_task"] != "pending_metadata_extraction":
        e["prediction_task"] = a["prediction_task"]
        stats["prediction_task_filled"] += 1

    # Add scope flag
    e["is_cohort_retrospective_binary"] = bool(a.get("is_cohort_retrospective_binary"))
    if a.get("is_cohort_retrospective_binary"):
        stats["cohort_binary"] += 1
    else:
        non_cohort.append(eid)
        stats["non_cohort"] += 1

    # Sample size if available
    if a.get("sample_size"):
        e["sample_size"] = a["sample_size"]
        stats["sample_size_filled"] += 1

    # Audit findings sub-block
    flags = a.get("anomaly_flags", [])
    e["audit_findings"] = {
        "is_peer_review_file": a.get("is_peer_review_file", False),
        "title_substring_match": a.get("title_substring_match", False),
        "anomaly_flags": flags,
        "confidence": a.get("confidence", "low"),
        "evidence_basis": a.get("evidence_basis", ""),
        "audited_at_utc": ts,
    }

    # Special handling
    if "pdf_corrupt_or_empty" in flags:
        e["_pdf_status"] = "corrupt_needs_redownload"
        corrupt.append(eid)
        stats["corrupt_pdfs"] += 1

    if "topic_not_medical_ml" in flags:
        e["out_of_scope_reason"] = "not_medical_ml"
        out_of_scope.append(eid)
        stats["out_of_scope"] += 1

    applied += 1

# Provenance audit record
kb.setdefault("provenance", {}).setdefault("integrity_audits", []).append({
    "audited_at_utc": ts,
    "method": "5 parallel agents performed strict per-entry audit (PDF↔title alignment, structured extraction, anomaly flagging) on 217 PR-EXP entries",
    "result": {
        "entries_audited": applied,
        "data_type_filled": stats["data_type_filled"],
        "prediction_task_filled": stats["prediction_task_filled"],
        "cohort_retrospective_binary": stats["cohort_binary"],
        "non_cohort": stats["non_cohort"],
        "corrupt_pdfs_flagged": stats["corrupt_pdfs"],
        "out_of_scope_flagged": stats["out_of_scope"],
        "corrupt_pdf_ids": corrupt,
        "out_of_scope_ids": out_of_scope,
    },
    "ip_compliance_note": "Agents extracted only structured field labels (categorical data_type, one-line synthesized prediction_task, boolean validation flags) and brief structural evidence_basis. NO reviewer concern text, abstracts, or paper text was reproduced into KB fields.",
})

KB_PATH.write_text(json.dumps(kb, indent=2, ensure_ascii=False))

# Summary
Path("/tmp/merge-audit-summary.json").write_text(json.dumps({
    "stats": dict(stats),
    "corrupt_pdf_ids": corrupt,
    "out_of_scope_ids": out_of_scope,
    "applied_to_entries": applied,
}, indent=2))

print(f"\n=== Merge summary ===")
print(f"Entries audited: {applied}")
for k, v in sorted(stats.items()):
    print(f"  {k}: {v}")
print(f"\nCorrupt PDFs needing redownload: {corrupt}")
print(f"Out-of-scope (not medical ML): {out_of_scope}")
