#!/usr/bin/env python3
"""
Fail-closed hygiene gate for the peer-review knowledge base.

Validates ``references/case-studies/peer-review-kb.json`` against the
contracts that retrieval and RAG ranking depend on:

1. Every value in a concern's ``mlgg_gates`` must be a gate name
   registered in ``scripts/core/_gate_registry.GATE_REGISTRY``.
2. Every concern's ``category`` must be in the 13-category allowlist
   defined by ``scripts/review/backfill_peer_review_gates.CATEGORY_TO_GATES``.
3. Every concern's ``severity`` must be one of
   {"CRITICAL", "HIGH", "MEDIUM", "LOW"}.
4. Every ``mlgg_rules`` entry must match the accepted rule-id pattern
   (short form like "S01" / "M01" or legacy "MLGG-X##").

The script fixed today 13 invalid refs that slipped in during a batch
KB ingestion. Without a CI-run hygiene gate the same class of bug will
recur every time a new batch of papers is added. This is the mitigation.

Behavior
--------
- Lenient mode (default): emits warnings for each violation so authors
  can see the debt during development.
- Strict mode (``--strict``): warnings promote to failures, exit code 2.
  Wire this into pre-commit and CI.

Output
------
Machine-readable JSON report via ``--report``; exit 0 (clean) / 2 (dirty).
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core")
_REVIEW_DIR = str(_Path(__file__).resolve().parent.parent / "review")
for _d in (_CORE_DIR, _REVIEW_DIR):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

import argparse
import json
import re
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
DEFAULT_KB = REPO_ROOT / "references" / "case-studies" / "peer-review-kb.json"

VALID_SEVERITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})

# Rule ids are either the short canonical form from CLAUDE.md's
# non-negotiable-rules table (letter + 2-3 digits, e.g. "M01", "S01",
# "F02") or the legacy "MLGG-X##" form left over from earlier
# ingestion. Either is acceptable; free-form strings are not.
_RULE_RE = re.compile(r"^(?:MLGG-)?[A-Z]\d{2,3}$")

# Keep these in sync with remediations in register_remediations below.
_CODES = {
    "HYG-001": "kb_not_found",
    "HYG-002": "kb_invalid_json",
    "HYG-003": "kb_missing_entries_block",
    "HYG-004": "invalid_gate_ref",
    "HYG-005": "invalid_category",
    "HYG-006": "invalid_severity",
    "HYG-007": "invalid_rule_id",
    "HYG-008": "registry_import_failed",
    "HYG-009": "category_allowlist_import_failed",
}


register_remediations({
    "kb_not_found": (
        "peer-review-kb.json not found. Expected path: "
        "references/case-studies/peer-review-kb.json."
    ),
    "kb_invalid_json": "peer-review-kb.json is not valid JSON. Run a JSON linter.",
    "kb_missing_entries_block": (
        "peer-review-kb.json top-level must contain an 'entries' list of "
        "paper objects."
    ),
    "invalid_gate_ref": (
        "A concern's mlgg_gates list references a gate name that is not "
        "in scripts/core/_gate_registry.GATE_REGISTRY. Either fix the "
        "typo, or if the gate name is correct but newly added, register "
        "it in _gate_registry.py. Hard-fail because retrieve_by_gate() "
        "and RAG ranking return an empty set for unknown gates — the "
        "citation is effectively lost."
    ),
    "invalid_category": (
        "A concern's category is not in the 13-category allowlist "
        "defined in scripts/review/backfill_peer_review_gates.py "
        "CATEGORY_TO_GATES. Fix the category to one of those 13."
    ),
    "invalid_severity": (
        "A concern's severity must be one of CRITICAL / HIGH / MEDIUM / "
        "LOW (uppercase). The retrieval module sorts by severity and "
        "will drop unknown values to the bottom of the ranking."
    ),
    "invalid_rule_id": (
        "mlgg_rules entries must match ^(?:MLGG-)?[A-Z]\\d{2,3}$. Short "
        "canonical form per CLAUDE.md (e.g., 'M01', 'S01') is preferred; "
        "legacy 'MLGG-X##' is also accepted."
    ),
    "registry_import_failed": (
        "Could not import GATE_REGISTRY from scripts/core/_gate_registry.py. "
        "The hygiene gate depends on it to validate mlgg_gates references."
    ),
    "category_allowlist_import_failed": (
        "Could not import CATEGORY_TO_GATES from "
        "scripts/review/backfill_peer_review_gates.py. The allowlist of "
        "13 categories lives there."
    ),
})


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kb", type=Path, default=DEFAULT_KB,
                   help="Path to peer-review-kb.json")
    p.add_argument("--report", help="Optional output JSON report path")
    p.add_argument("--strict", action="store_true",
                   help="Promote warnings to failures (CI / pre-commit mode)")
    return p.parse_args()


def load_gate_registry(failures: List[Dict[str, Any]]) -> set:
    try:
        from _gate_registry import GATE_REGISTRY  # type: ignore
    except Exception as exc:
        add_issue(failures, "registry_import_failed",
                  "Could not import GATE_REGISTRY.",
                  {"error": str(exc)})
        return set()
    return set(GATE_REGISTRY.keys())


def load_category_allowlist(failures: List[Dict[str, Any]]) -> set:
    try:
        from backfill_peer_review_gates import CATEGORY_TO_GATES  # type: ignore
    except Exception as exc:
        add_issue(failures, "category_allowlist_import_failed",
                  "Could not import CATEGORY_TO_GATES.",
                  {"error": str(exc)})
        return set()
    return set(CATEGORY_TO_GATES.keys())


def validate_concern(
    entry_id: str,
    concern: Dict[str, Any],
    registered_gates: set,
    allowed_categories: set,
    warnings: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Validate one concern in place; append warnings. Returns per-
    violation counts for the summary."""
    counts = {"gate": 0, "category": 0, "severity": 0, "rule": 0}
    cid = concern.get("concern_id") or f"{entry_id}?unknown"

    # mlgg_gates
    gates = concern.get("mlgg_gates", [])
    if isinstance(gates, list):
        for g in gates:
            if not isinstance(g, str) or g not in registered_gates:
                counts["gate"] += 1
                add_issue(
                    warnings, "invalid_gate_ref",
                    f"Concern '{cid}' references unknown gate.",
                    {
                        "concern_id": cid,
                        "paper_id": entry_id,
                        "invalid_gate": g,
                        "hint": (
                            "Check scripts/core/_gate_registry.py for the "
                            "canonical list."
                        ),
                    },
                )

    # category
    cat = concern.get("category")
    if cat is None or cat not in allowed_categories:
        counts["category"] += 1
        add_issue(
            warnings, "invalid_category",
            f"Concern '{cid}' has category outside the 13-allowlist.",
            {
                "concern_id": cid,
                "paper_id": entry_id,
                "actual_category": cat,
                "allowed_categories": sorted(allowed_categories),
            },
        )

    # severity
    sev = concern.get("severity")
    if sev not in VALID_SEVERITIES:
        counts["severity"] += 1
        add_issue(
            warnings, "invalid_severity",
            f"Concern '{cid}' has invalid severity.",
            {
                "concern_id": cid,
                "paper_id": entry_id,
                "actual_severity": sev,
                "allowed": sorted(VALID_SEVERITIES),
            },
        )

    # mlgg_rules (optional, but when present must match pattern)
    rules = concern.get("mlgg_rules", [])
    if isinstance(rules, list):
        for r in rules:
            if not isinstance(r, str) or not _RULE_RE.match(r):
                counts["rule"] += 1
                add_issue(
                    warnings, "invalid_rule_id",
                    f"Concern '{cid}' has malformed mlgg_rules entry.",
                    {
                        "concern_id": cid,
                        "paper_id": entry_id,
                        "invalid_rule": r,
                    },
                )

    return counts


def main() -> int:
    args = parse_args()
    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    kb_path = Path(args.kb).expanduser().resolve()
    if not kb_path.exists():
        add_issue(failures, "kb_not_found",
                  "peer-review-kb.json not found.",
                  {"path": str(kb_path)})
        return finish(args, failures, warnings, {"kb_path": str(kb_path)})

    try:
        with kb_path.open("r", encoding="utf-8") as fh:
            kb = json.load(fh)
    except Exception as exc:
        add_issue(failures, "kb_invalid_json",
                  "peer-review-kb.json is not valid JSON.",
                  {"path": str(kb_path), "error": str(exc)})
        return finish(args, failures, warnings, {"kb_path": str(kb_path)})

    entries = kb.get("entries")
    if not isinstance(entries, list):
        add_issue(failures, "kb_missing_entries_block",
                  "peer-review-kb.json missing 'entries' list.",
                  {"path": str(kb_path)})
        return finish(args, failures, warnings, {"kb_path": str(kb_path)})

    registered_gates = load_gate_registry(failures)
    allowed_categories = load_category_allowlist(failures)
    if not registered_gates or not allowed_categories:
        # Cannot proceed without the source-of-truth lists.
        return finish(args, failures, warnings, {"kb_path": str(kb_path)})

    total_concerns = 0
    totals = {"gate": 0, "category": 0, "severity": 0, "rule": 0}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id", "?")
        concerns = entry.get("reviewer_concerns", [])
        if not isinstance(concerns, list):
            continue
        for concern in concerns:
            if not isinstance(concern, dict):
                continue
            total_concerns += 1
            bucket = validate_concern(
                entry_id, concern, registered_gates, allowed_categories,
                warnings,
            )
            for k, v in bucket.items():
                totals[k] += v

    summary = {
        "kb_path": str(kb_path),
        "kb_version": kb.get("version") or kb.get("contract_version"),
        "total_papers": len(entries),
        "total_concerns": total_concerns,
        "invalid_gate_refs": totals["gate"],
        "invalid_categories": totals["category"],
        "invalid_severities": totals["severity"],
        "invalid_rule_ids": totals["rule"],
        "total_violations": sum(totals.values()),
        "registered_gates_count": len(registered_gates),
        "allowed_categories_count": len(allowed_categories),
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
        gate_name="kb_hygiene_check",
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
        gate_name="kb_hygiene_check",
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
