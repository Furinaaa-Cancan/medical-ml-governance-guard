#!/usr/bin/env python3
"""
Fail-closed gate for clinician review status of the disease definition KB.

Scans ``references/methodology/disease-definition-knowledge-base.json`` and
refuses publication-grade claims if any disease entry's ``provenance.source``
is ``llm_compiled`` (or ``clinician_review_status`` is ``pending``).

Behavior
--------
- Warning mode (default): emits warnings for each unreviewed disease so
  exploratory runs stay functional while making the debt visible.
- Strict mode (``--strict``): warnings are promoted to failures and the gate
  exits with code 2 — this is what publication-grade pipelines invoke.

Remediation
-----------
1. Run ``scripts/diagnostics/generate_disease_kb_review_sheets.py`` to render
   one Markdown review sheet per disease under ``evidence/disease_kb_review/``.
2. A clinician completes each checklist against the cited guideline.
3. Edit the KB entry's ``provenance`` block per the sheet's Sign-off section
   (``source``: ``clinician_reviewed``, plus ``last_reviewed``, ``reviewer``,
   ``reviewed_against``).
4. Re-run with ``--strict``; the gate passes when all diseases are
   clinician-reviewed.
"""
from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from _gate_framework import (
    GateIssue,
    Severity,
    build_report_envelope,
    get_remediation,
    print_gate_summary,
    register_remediations,
)
from _gate_utils import add_issue


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_KB = REPO_ROOT / "references" / "methodology" / "disease-definition-knowledge-base.json"

# Statuses that constitute a clinician sign-off. Keeping these as a set (not
# a single string) lets future reviewers use domain-specific terminal states
# (e.g., "specialty_reviewed") without breaking the gate.
APPROVED_STATUSES = frozenset({
    "clinician_reviewed",
    "specialist_reviewed",
    "approved",
    "signed_off",
})

# Explicit non-terminal statuses — when clinician_review_status is one of
# these, the entry is NOT approved regardless of what 'source' claims. This
# prevents a stale 'source: clinician_reviewed' from masking an in-flight
# re-review that set status back to pending.
PENDING_STATUSES = frozenset({
    "pending",
    "unreviewed",
    "in_review",
    "under_review",
    "awaiting_review",
})


register_remediations({
    "kb_not_found": (
        "Disease KB file not found. Expected path: "
        "references/methodology/disease-definition-knowledge-base.json."
    ),
    "kb_invalid_json": "Disease KB is not valid JSON. Run a JSON linter.",
    "kb_missing_diseases_block": (
        "Disease KB top-level is missing a 'diseases' object."
    ),
    "clinician_review_pending": (
        "Disease entry is still LLM-compiled and pending clinician sign-off. "
        "Run scripts/diagnostics/generate_disease_kb_review_sheets.py to "
        "render review sheets, have a clinician complete the checklist "
        "against the cited guideline, then update the entry's provenance "
        "block (source: clinician_reviewed, plus last_reviewed, reviewer, "
        "reviewed_against). "
        "This gate passes only when every disease in the KB has a terminal "
        "approved status; this is a hard requirement for NC/Nat Med / Lancet "
        "Digital Health-level publication claims about cohort definitions."
    ),
    "clinician_review_provenance_missing": (
        "Disease entry has no 'provenance' block. Add one declaring the "
        "source (llm_compiled / clinician_reviewed) and review status; "
        "see references/methodology/DISEASE_KB_REVIEW.md."
    ),
})


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kb", type=Path, default=DEFAULT_KB,
                   help="Path to disease KB JSON")
    p.add_argument("--report", help="Optional output JSON report path")
    p.add_argument("--strict", action="store_true",
                   help="Promote warnings to failures (publication-grade mode)")
    return p.parse_args()


def classify_disease(
    key: str, entry: Dict[str, Any]
) -> Tuple[str, Dict[str, Any]]:
    """Return (status_bucket, details) for one disease entry.

    Buckets:
        "approved" — ALL three reviewer-binding fields present:
                       (a) clinician_review_status in APPROVED_STATUSES,
                       (b) non-empty 'reviewer',
                       (c) non-empty 'last_reviewed'.
                     The 'source' field alone is NEVER sufficient (W11-F2:
                     closed a 1-line JSON spoofing hole where setting
                     "source": "approved" bypassed the entire fail-closed
                     publication_gate without binding to any reviewer).
        "pending"  — clinician_review_status is explicitly a pending value.
        "missing"  — no provenance block at all, OR provenance present but
                     missing one or more reviewer-binding fields required
                     for approval (e.g., source-only approval, status
                     approved but reviewer/last_reviewed empty). Surfaced
                     under the same warning code as no-provenance so audit
                     consumers see a single "incomplete provenance" signal.
    """
    prov = entry.get("provenance")
    if not isinstance(prov, dict):
        return "missing", {
            "disease": key,
            "name": entry.get("name", key),
            "reason": "no provenance block",
        }

    source = str(prov.get("source", "")).strip().lower()
    status = str(prov.get("clinician_review_status", "")).strip().lower()
    reviewer = str(prov.get("reviewer") or "").strip()
    last_reviewed = str(prov.get("last_reviewed") or "").strip()

    # A pending status is a hard override: if a reviewer explicitly marked
    # the entry as not-yet-approved, no 'source' value can overrule it.
    if status in PENDING_STATUSES:
        return "pending", {
            "disease": key,
            "name": entry.get("name", key),
            "source": source or None,
            "clinician_review_status": status,
        }

    # W11-F2: approval requires the reviewer-binding triple. The 'source'
    # field is metadata about how the entry was authored; only the
    # clinician_review_status + reviewer + last_reviewed fields together
    # constitute an actual sign-off audit trail.
    status_approved = status in APPROVED_STATUSES
    if status_approved and reviewer and last_reviewed:
        return "approved", {
            "disease": key,
            "name": entry.get("name", key),
            "source": source or None,
            "clinician_review_status": status or None,
            "reviewer": prov.get("reviewer"),
            "last_reviewed": prov.get("last_reviewed"),
            "reviewed_against": prov.get("reviewed_against"),
        }

    # Provenance present but incomplete — surface as "missing" so the
    # existing warning path (clinician_review_provenance_missing) flags it.
    # Specifically catches: source-only approval (W11-F2 spoofing hole),
    # and approved status without reviewer or date binding.
    if status_approved or source in APPROVED_STATUSES:
        missing_fields = []
        if not status_approved:
            missing_fields.append("clinician_review_status")
        if not reviewer:
            missing_fields.append("reviewer")
        if not last_reviewed:
            missing_fields.append("last_reviewed")
        return "missing", {
            "disease": key,
            "name": entry.get("name", key),
            "source": source or None,
            "clinician_review_status": status or None,
            "reviewer": prov.get("reviewer"),
            "last_reviewed": prov.get("last_reviewed"),
            "reason": (
                "incomplete provenance — approval requires "
                "clinician_review_status in APPROVED_STATUSES plus non-empty "
                "reviewer and last_reviewed; missing: "
                + ", ".join(missing_fields)
            ),
        }

    return "pending", {
        "disease": key,
        "name": entry.get("name", key),
        "source": source or None,
        "clinician_review_status": status or "pending",
    }


def main() -> int:
    args = parse_args()
    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    kb_path = Path(args.kb).expanduser().resolve()
    if not kb_path.exists():
        add_issue(failures, "kb_not_found",
                  "Disease KB file not found.",
                  {"path": str(kb_path)})
        return finish(args, failures, warnings, summary={"kb_path": str(kb_path)})

    try:
        with kb_path.open("r", encoding="utf-8") as fh:
            kb = json.load(fh)
        if not isinstance(kb, dict):
            raise ValueError("KB root must be a JSON object.")
    except Exception as exc:
        add_issue(failures, "kb_invalid_json",
                  "Disease KB is not valid JSON.",
                  {"path": str(kb_path), "error": str(exc)})
        return finish(args, failures, warnings, summary={"kb_path": str(kb_path)})

    diseases = kb.get("diseases")
    if not isinstance(diseases, dict) or not diseases:
        add_issue(failures, "kb_missing_diseases_block",
                  "Disease KB missing non-empty 'diseases' object.",
                  {"path": str(kb_path)})
        return finish(args, failures, warnings, summary={"kb_path": str(kb_path)})

    buckets: Dict[str, List[Dict[str, Any]]] = {
        "approved": [], "pending": [], "missing": [],
    }
    for key, entry in diseases.items():
        bucket, details = classify_disease(key, entry)
        buckets[bucket].append(details)

    for details in buckets["missing"]:
        add_issue(warnings, "clinician_review_provenance_missing",
                  f"Disease entry '{details['disease']}' has no provenance block.",
                  details)
    for details in buckets["pending"]:
        add_issue(warnings, "clinician_review_pending",
                  f"Disease '{details['disease']}' is LLM-compiled and "
                  f"not yet clinician-reviewed.",
                  details)

    summary = {
        "kb_path": str(kb_path),
        "kb_version": kb.get("version"),
        "total_diseases": len(diseases),
        "approved_count": len(buckets["approved"]),
        "pending_count": len(buckets["pending"]),
        "missing_provenance_count": len(buckets["missing"]),
        "approved_diseases": [d["disease"] for d in buckets["approved"]],
        "pending_diseases": [d["disease"] for d in buckets["pending"]],
    }
    return finish(args, failures, warnings, summary)


def finish(
    args: argparse.Namespace,
    failures: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    summary: Dict[str, Any],
) -> int:
    from _gate_utils import get_gate_elapsed, write_json as _write_report

    should_fail = bool(failures) or (args.strict and bool(warnings))
    status = "fail" if should_fail else "pass"

    fi = [GateIssue.from_legacy(f, Severity.ERROR) for f in failures]
    wi = [GateIssue.from_legacy(w, Severity.WARNING) for w in warnings]
    for issue in fi + wi:
        if not issue.remediation:
            issue.remediation = get_remediation(issue.code)

    report = build_report_envelope(
        gate_name="disease_kb_review_check",
        status=status,
        strict_mode=bool(args.strict),
        failures=fi,
        warnings=wi,
        summary=summary,
        input_files={"kb": summary.get("kb_path", "")},
    )

    if args.report:
        _write_report(Path(args.report).expanduser().resolve(), report)

    print_gate_summary(
        gate_name="disease_kb_review_check",
        status=status,
        failures=fi,
        warnings=wi,
        strict=bool(args.strict),
        elapsed=get_gate_elapsed(),
    )
    return 2 if should_fail else 0


if __name__ == "__main__":
    from _gate_utils import start_gate_timer
    start_gate_timer()
    raise SystemExit(main())
