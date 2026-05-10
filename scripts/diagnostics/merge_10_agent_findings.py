"""Merge 10-agent wave findings into peer-review-kb.json.

Applies, idempotently:
  - A1's 12 cohort-binary flips (chunk-1 re-audit disagreements)
  - A8's anomaly_flag cleanup ("title_does_not_match_pdf" 100% FP — clear all 25)
  - A9's 33 data_type/prediction_task backfills + out-of-scope marking
  - Provenance audit-trail entry for the wave

CRITICAL: per CLAUDE.md, this script is the ONLY writer to peer-review-kb.json
during this wave. Run with --dry-run first to produce a review report. The
human reviewer must approve the report before --apply runs.

Usage:
  python3 scripts/diagnostics/merge_10_agent_findings.py --dry-run > paper/kb-merge-10agent-dryrun.md
  # ...human review...
  python3 scripts/diagnostics/merge_10_agent_findings.py --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KB_PATH = ROOT / "references" / "case-studies" / "peer-review-kb.json"
A1_PATH = Path("/tmp/agent01-chunk1-reaudit.json")
A8_PATH = Path("/tmp/agent08-title-flag-recheck.json")
A9_PATH = Path("/tmp/agent09-backfill.json")

WAVE_ID = "10-agent-wave-2026-05-10"
NOW_UTC = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_agent_outputs() -> tuple[list, dict, list]:
    a1 = json.loads(A1_PATH.read_text())
    a8 = json.loads(A8_PATH.read_text())
    a9 = json.loads(A9_PATH.read_text())
    return a1, a8, a9


def load_kb() -> dict:
    return json.loads(KB_PATH.read_text())


def build_changeset(kb: dict, a1: list, a8: dict, a9: list):
    """Compute the diff plan without mutating kb."""
    by_id = {e["id"]: e for e in kb.get("entries", [])}
    plan: dict[str, dict] = {}

    # ------------- A1: 12 cohort-binary flips -------------
    a1_flips = [r for r in a1 if r.get("agreement_with_chunk1") == "disagree"]
    for r in a1_flips:
        eid = r["id"]
        entry = by_id.get(eid)
        if entry is None:
            plan.setdefault(eid, {"missing": True, "actions": []})
            continue
        cur = entry.get("is_cohort_retrospective_binary")
        new = bool(r.get("is_cohort_retrospective_binary"))
        if cur is True:
            continue  # already correct
        plan.setdefault(eid, {"actions": []})
        plan[eid]["actions"].append({
            "agent": "A1",
            "field": "is_cohort_retrospective_binary",
            "from": cur,
            "to": new,
            "evidence": r.get("evidence_basis", "")[:200],
        })

    # ------------- A8: clear title-mismatch flag -------------
    # anomaly_flags lives under audit_findings.anomaly_flags
    a8_results = a8.get("results", [])
    for r in a8_results:
        eid = r["id"]
        entry = by_id.get(eid)
        if entry is None:
            plan.setdefault(eid, {"missing": True, "actions": []})
            continue
        af = entry.get("audit_findings") or {}
        flags = af.get("anomaly_flags") or []
        if "title_does_not_match_pdf" not in flags:
            continue
        plan.setdefault(eid, {"actions": []})
        plan[eid]["actions"].append({
            "agent": "A8",
            "field": "audit_findings.anomaly_flags",
            "op": "remove",
            "value": "title_does_not_match_pdf",
            "evidence": r.get("evidence_basis", "")[:200],
        })

    # ------------- A9: 33 data_type / prediction_task backfills -------------
    for r in a9:
        eid = r["id"]
        entry = by_id.get(eid)
        if entry is None:
            plan.setdefault(eid, {"missing": True, "actions": []})
            continue
        plan.setdefault(eid, {"actions": []})

        new_dt_raw = r.get("new_data_type") or ""
        new_dt = new_dt_raw.removeprefix("[NEW]").strip()
        is_new_label = new_dt_raw.startswith("[NEW]")
        cur_dt = entry.get("data_type")
        if new_dt and new_dt != cur_dt:
            plan[eid]["actions"].append({
                "agent": "A9",
                "field": "data_type",
                "from": cur_dt,
                "to": new_dt,
                "is_new_label": is_new_label,
            })
            if is_new_label:
                # mark vocabulary status so reviewers can find unblessed labels
                plan[eid]["actions"].append({
                    "agent": "A9",
                    "field": "_data_type_vocab_status",
                    "from": entry.get("_data_type_vocab_status"),
                    "to": "new_unreviewed",
                })

        new_pt = r.get("new_prediction_task")
        cur_pt = entry.get("prediction_task")
        if new_pt and new_pt != cur_pt:
            plan[eid]["actions"].append({
                "agent": "A9",
                "field": "prediction_task",
                "from": (cur_pt or "")[:80],
                "to": new_pt[:80],
            })

        new_conf = r.get("new_confidence")
        cur_conf = (entry.get("audit_findings") or {}).get("confidence")
        if new_conf and new_conf != cur_conf:
            plan[eid]["actions"].append({
                "agent": "A9",
                "field": "audit_findings.confidence",
                "from": cur_conf,
                "to": new_conf,
            })

        # Out-of-scope marking
        a9_cohort = r.get("is_cohort_retrospective_binary")
        cur_cohort = entry.get("is_cohort_retrospective_binary")
        if a9_cohort is False:
            is_basic_biology = "preclinical_basic_biology" in str(r.get("new_data_type", ""))
            new_oos_reason = (
                "preclinical_basic_biology" if is_basic_biology else "non_cohort_binary_modality"
            )
            cur_oos_reason = entry.get("out_of_scope_reason")
            if cur_cohort is not False:
                plan[eid]["actions"].append({
                    "agent": "A9",
                    "field": "is_cohort_retrospective_binary",
                    "from": cur_cohort,
                    "to": False,
                })
            # always refine OOS reason if A9 provides a more specific one
            if cur_oos_reason != new_oos_reason and (
                cur_oos_reason in (None, "not_medical_ml") or is_basic_biology
            ):
                plan[eid]["actions"].append({
                    "agent": "A9",
                    "field": "out_of_scope_reason",
                    "from": cur_oos_reason,
                    "to": new_oos_reason,
                })

    # ------------- A4: drop _pdf_status flags from re-downloaded PDFs -------------
    for eid in ("PR-EXP-0044", "PR-EXP-0080"):
        entry = by_id.get(eid)
        if entry is None or "_pdf_status" not in entry:
            continue
        plan.setdefault(eid, {"actions": []})
        plan[eid]["actions"].append({
            "agent": "A4",
            "field": "_pdf_status",
            "op": "delete",
            "from": entry.get("_pdf_status"),
            "to": None,
        })

    # Drop entries that ended with no actionable changes
    plan = {k: v for k, v in plan.items() if v.get("missing") or v.get("actions")}
    return plan


def apply_changeset(kb: dict, plan: dict) -> dict:
    """Mutate kb in-place per plan; return summary counts."""
    by_id = {e["id"]: e for e in kb.get("entries", [])}
    counts = {"a1_flips": 0, "a8_clears": 0, "a9_changes": 0, "out_of_scope": 0}

    for eid, p in plan.items():
        if p.get("missing"):
            continue
        entry = by_id[eid]
        for a in p["actions"]:
            field = a["field"]
            agent = a["agent"]
            if field == "audit_findings.anomaly_flags" and a.get("op") == "remove":
                af = entry.setdefault("audit_findings", {})
                flags = af.get("anomaly_flags") or []
                af["anomaly_flags"] = [f for f in flags if f != a["value"]]
                if not af["anomaly_flags"]:
                    af.pop("anomaly_flags", None)
                counts["a8_clears"] += 1
            elif field == "audit_findings.confidence":
                af = entry.setdefault("audit_findings", {})
                af["confidence"] = a["to"]
                counts["a9_changes"] += 1
            elif field == "out_of_scope_reason":
                entry["out_of_scope_reason"] = a["to"]
                counts["out_of_scope"] += 1
            else:
                entry[field] = a["to"]
                if field == "is_cohort_retrospective_binary":
                    if agent == "A1":
                        counts["a1_flips"] += 1
                    elif agent == "A9":
                        counts["a9_changes"] += 1
                else:
                    counts["a9_changes"] += 1

    # Provenance audit-trail entry
    kb.setdefault("provenance", {}).setdefault("integrity_audits", []).append({
        "audit_id": WAVE_ID,
        "audited_at_utc": NOW_UTC,
        "method": "10-agent parallel review",
        "summary": {
            "A1_chunk1_reaudit_flips": counts["a1_flips"],
            "A8_title_mismatch_flags_cleared": counts["a8_clears"],
            "A9_backfill_changes": counts["a9_changes"],
            "A9_out_of_scope_marked": counts["out_of_scope"],
        },
        "documented_in": [
            "paper/outline-v0.2.md",
            "paper/prisma-flow.md",
            "paper/lint-audit-110.md",
            "paper/fig4-confusion-matrix.md",
        ],
        "agents": {
            "A1": "chunk-1 re-audit; 12 disagreements → cohort_binary=true",
            "A2": "mlgg-lint on 92 repos; 48 with findings; 448 total",
            "A3": "TP/FP audit; aggregate TP=76%; R021/R008/R004 flagged",
            "A4": "large-PDF wget resume; PR-EXP-0044/0080 now valid",
            "A5": "R029 credentials-in-availability rule; 116/116 tests",
            "A6": "PRISMA-2020 flow documentation",
            "A7": "Fig 4 confusion matrix; n=5 baseline (expansion pending)",
            "A8": "title-mismatch flag recheck; 25/25 verbatim-absent FPs",
            "A9": "data_type/prediction_task backfill; 33 entries, 19 OOS",
            "A10": "outline-v0.2.md (455 lines) for target journals",
        },
    })
    return counts


def render_report(plan: dict, kb_total: int, kb: dict | None = None) -> str:
    by_id = {e["id"]: e for e in (kb or {}).get("entries", [])}
    lines = [
        "# 10-agent wave KB merge — DRY RUN report",
        f"\nGenerated: {NOW_UTC}",
        f"\nKB entries: {kb_total}",
        f"\nEntries to be modified: {sum(1 for v in plan.values() if not v.get('missing'))}",
        f"Entries referenced but missing in KB: {sum(1 for v in plan.values() if v.get('missing'))}",
        "",
        "## A1 — chunk 1 cohort-binary flips",
        "",
        "| ID | from | to | evidence |",
        "|---|---|---|---|",
    ]
    for eid, p in sorted(plan.items()):
        for a in p.get("actions", []):
            if a.get("agent") == "A1" and a.get("field") == "is_cohort_retrospective_binary":
                lines.append(f"| {eid} | `{a['from']}` | `{a['to']}` | {a['evidence'][:90]} |")

    lines += [
        "",
        "## A8 — clear title_does_not_match_pdf flag",
        "",
        "| ID | evidence |",
        "|---|---|",
    ]
    for eid, p in sorted(plan.items()):
        for a in p.get("actions", []):
            if a.get("agent") == "A8":
                lines.append(f"| {eid} | {a['evidence'][:90]} |")

    lines += ["", "## A9 — backfill (data_type / prediction_task / confidence)", ""]
    for eid, p in sorted(plan.items()):
        a9_actions = [a for a in p.get("actions", []) if a.get("agent") == "A9"]
        if not a9_actions:
            continue
        lines.append(f"\n### {eid}")
        for a in a9_actions:
            f, t = a.get("from"), a.get("to")
            new_label = " ⚠️[NEW label]" if a.get("is_new_label") else ""
            lines.append(f"- **{a['field']}**: `{f}` → `{t}`{new_label}")

    a4_rows: list[str] = []
    for eid, p in sorted(plan.items()):
        for a in p.get("actions", []):
            if a.get("agent") == "A4" and a.get("op") == "delete":
                a4_rows.append(f"| {eid} | `{a['from']}` | delete field |")
    if a4_rows:
        lines += [
            "",
            "## A4 — drop _pdf_status flag (PDFs now valid after wget resume)",
            "",
            "| ID | from | action |",
            "|---|---|---|",
            *a4_rows,
        ]

    lines += [
        "",
        "## ⚠️ Borderline — needs human ruling",
        "",
        "| ID | issue |",
        "|---|---|",
    ]
    # 0151: A9 keeps cohort=True but data_type=omics (per CLAUDE.md, omics is out-of-scope regardless of binary head)
    if "PR-EXP-0151" in plan:
        lines.append("| PR-EXP-0151 | A9 relabels data_type → `wgs_somatic_mutations` (omics) but keeps cohort_binary=true. Per CLAUDE.md mlgg does NOT cover omics regardless of classification head — recommend forcing cohort=false + out_of_scope=`omics_modality`. **DRY-RUN does NOT do this; needs human ruling.** |")

    lines += [
        "",
        "## A9 — out-of-mlgg-scope marking",
        "",
        "Entries with `is_cohort_retrospective_binary=false`. Per CLAUDE.md, mlgg covers retrospective cohort binary classification only — these do **not** drop from the KB but are marked for cohort-only analyses.",
        "",
        "| ID | reason | data_type |",
        "|---|---|---|",
    ]
    for eid, p in sorted(plan.items()):
        a9_oos = [a for a in p.get("actions", []) if a.get("agent") == "A9" and a.get("field") == "out_of_scope_reason"]
        a9_dt = [a for a in p.get("actions", []) if a.get("agent") == "A9" and a.get("field") == "data_type"]
        if a9_oos:
            if a9_dt:
                dt = a9_dt[0]["to"]
            else:
                # fall back to current entry's data_type (no change action emitted)
                dt = (by_id.get(eid) or {}).get("data_type", "?")
            lines.append(f"| {eid} | {a9_oos[0]['to']} | `{dt}` |")

    lines += [
        "",
        "## Missing IDs (referenced by an agent but absent in KB)",
        "",
    ]
    missing = [eid for eid, p in sorted(plan.items()) if p.get("missing")]
    if missing:
        for eid in missing:
            lines.append(f"- {eid}")
    else:
        lines.append("_(none — all referenced IDs found in KB)_")

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Print plan to stdout, do not modify KB.")
    g.add_argument("--apply", action="store_true", help="Apply plan to KB.")
    ap.add_argument("--report-out", type=Path, default=ROOT / "paper" / "kb-merge-10agent-dryrun.md")
    args = ap.parse_args()

    a1, a8, a9 = load_agent_outputs()
    kb = load_kb()
    plan = build_changeset(kb, a1, a8, a9)
    report = render_report(plan, len(kb.get("entries", [])), kb)

    if args.dry_run:
        args.report_out.write_text(report)
        sys.stdout.write(report)
        sys.stderr.write(f"\n[dry-run] report written to {args.report_out}\n")
        return 0

    counts = apply_changeset(kb, plan)
    KB_PATH.write_text(json.dumps(kb, indent=2, ensure_ascii=False) + "\n")
    sys.stderr.write(f"[apply] KB written: {counts}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
