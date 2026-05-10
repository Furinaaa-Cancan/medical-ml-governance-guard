#!/usr/bin/env python3
"""Build confusion-matrix data for Fig 4.

Compares mlgg-lint findings against reviewer concerns for the 31-paper
"trustable subset" (cohort-binary scope + reviewer_concerns + PDF link).

Outputs:
  paper/fig4-data.json          machine-readable
  paper/fig4-confusion-matrix.md  table-only display

IP compliance: per-paper output uses ID only (e.g. "PR-001"); no concern
text is reproduced; only categorical gate / rule labels.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Volumes/Seagate/Skill/ml-leakage-guard")
KB_PATH = ROOT / "references/case-studies/peer-review-kb.json"
LINT_PATH = ROOT / "paper/lint-audit-results.json"
LINT_110_PATH = ROOT / "paper/lint-audit-110.json"  # may not exist yet
OUT_JSON = ROOT / "paper/fig4-data.json"
OUT_MD = ROOT / "paper/fig4-confusion-matrix.md"

# 8-category scheme. Map both reviewer-concern gates and lint rule_ids.
CATEGORIES = [
    "leakage",
    "imbalance",
    "threshold_calibration",
    "split_protocol",
    "evaluation",
    "model_selection",
    "feature_engineering",
    "reporting",
]

# Gate -> categories (a gate may map to multiple categories)
GATE_TO_CATEGORIES: dict[str, list[str]] = {
    "leakage_gate": ["leakage"],
    "imbalance_policy_gate": ["imbalance"],
    "calibration_dca_gate": ["threshold_calibration"],
    "split_protocol_gate": ["split_protocol"],
    "evaluation_quality_gate": ["evaluation"],
    "clinical_metrics_gate": ["evaluation"],
    "ci_matrix_gate": ["evaluation"],
    "model_selection_audit_gate": ["model_selection"],
    "tuning_leakage_gate": ["model_selection"],
    "feature_engineering_audit_gate": ["feature_engineering"],
    "feature_lineage_gate": ["feature_engineering"],
    "missingness_policy_gate": ["feature_engineering"],
    "reporting_bias_gate": ["reporting"],
    "publication_gate": ["reporting"],
}

# Rule -> categories (per the user-supplied scheme)
RULE_TO_CATEGORIES: dict[str, list[str]] = {
    "R001": ["leakage"],
    "R002": ["leakage"],
    "R003": ["leakage", "imbalance"],
    "R004": ["split_protocol"],
    "R005": ["threshold_calibration"],
    "R006": ["leakage", "feature_engineering"],
    "R007": ["leakage"],
    "R008": ["split_protocol"],
    "R009": ["evaluation", "reporting"],
    "R010": ["evaluation"],
    "R011": ["leakage"],
    "R012": ["evaluation"],
    "R013": ["reporting"],
    "R017": ["leakage"],
    "R020": ["feature_engineering"],
    "R021": ["model_selection"],
    "R022": ["evaluation"],
    "R023": ["leakage", "feature_engineering"],
    "R024": ["leakage", "feature_engineering"],
    "R025": ["leakage"],
    "R026": ["leakage", "feature_engineering"],
    "R027": ["leakage"],
}


def load_kb() -> dict:
    with KB_PATH.open() as f:
        return json.load(f)


def load_lint() -> dict[str, list[str] | None]:
    """Return {paper_id: [rule_id, ...] or None}.

    None  = repo not audited (clone failed / non-Python / payload null)
    []    = audited and no findings
    [...] = audited findings; rule_ids may include error codes (E000) ignored
    """
    audits: dict[str, list[str] | None] = {}

    if LINT_110_PATH.exists():
        sources = [LINT_PATH, LINT_110_PATH]
    else:
        sources = [LINT_PATH]

    for src in sources:
        with src.open() as f:
            data = json.load(f)
        for entry in data.get("results", []):
            pid = entry["id"]
            payload = (entry.get("lint") or {}).get("payload")
            if payload is None:
                # Don't overwrite a successful audit if same id appears twice
                audits.setdefault(pid, None)
                continue
            rules = [
                f["rule_id"]
                for f in payload
                if isinstance(f, dict)
                and f.get("rule_id", "").startswith("R")
            ]
            audits[pid] = rules
    return audits


def select_trustable(kb: dict) -> list[dict]:
    out = []
    for entry in kb.get("entries", []):
        if not entry.get("is_cohort_retrospective_binary"):
            continue
        if not entry.get("reviewer_concerns"):
            continue
        pdf = entry.get("peer_review_pdf_path") or ""
        if not pdf:
            continue
        out.append(entry)
    return out


def reviewer_categories_for(entry: dict) -> set[str]:
    cats: set[str] = set()
    for concern in entry.get("reviewer_concerns", []):
        for g in concern.get("mlgg_gates", []) or []:
            cats.update(GATE_TO_CATEGORIES.get(g, []))
    return cats


def lint_categories_for(rule_ids: list[str]) -> set[str]:
    cats: set[str] = set()
    for r in rule_ids:
        cats.update(RULE_TO_CATEGORIES.get(r, []))
    return cats


def main() -> None:
    kb = load_kb()
    lint = load_lint()
    trustable = select_trustable(kb)
    assert len(trustable) == 31, f"expected 31, got {len(trustable)}"

    # Per-paper records (audited only, IP-compliant: id only)
    per_paper: list[dict] = []

    for entry in trustable:
        pid = entry["id"]
        rev_cats = reviewer_categories_for(entry)
        rev_gates = sorted({
            g for c in entry["reviewer_concerns"]
            for g in (c.get("mlgg_gates") or [])
        })
        lint_rules = lint.get(pid)  # None if unaudited
        if lint_rules is None:
            audited = False
            lint_cats: set[str] = set()
            unique_rules: list[str] = []
        else:
            audited = True
            unique_rules = sorted(set(lint_rules))
            lint_cats = lint_categories_for(lint_rules)

        per_paper.append({
            "id": pid,
            "audited": audited,
            "reviewer_gates": rev_gates,
            "reviewer_categories": sorted(rev_cats),
            "lint_rules_unique": unique_rules,
            "lint_rule_total_hits": (
                len(lint_rules) if lint_rules is not None else None
            ),
            "lint_categories": sorted(lint_cats),
            "category_vector": {
                cat: {
                    "reviewer": cat in rev_cats,
                    "mlgg": cat in lint_cats,
                }
                for cat in CATEGORIES
            },
        })

    audited_papers = [p for p in per_paper if p["audited"]]
    n_audited = len(audited_papers)
    n_total = len(per_paper)

    # KB curation gap: papers in trustable subset whose reviewer_concerns
    # exist but contain no mlgg_gates -> we cannot build a reviewer category
    # vector for them. Flag for downstream curation.
    papers_without_gates = [
        p["id"] for p in per_paper
        if not any(p["reviewer_gates"])
    ]
    audited_with_gates = [
        p for p in audited_papers if p["reviewer_gates"]
    ]
    n_audited_with_gates = len(audited_with_gates)

    # Aggregate confusion matrix per category. Restrict to papers that are
    # both audited (lint payload available) AND have reviewer_concerns with
    # at least one mlgg_gate populated; otherwise we cannot build a reviewer
    # category vector. Papers with concerns-but-no-gates are flagged
    # separately as a KB-curation gap.
    per_category: dict[str, dict] = {}
    for cat in CATEGORIES:
        tp = tn = fp = fn = 0
        for p in audited_with_gates:
            r = p["category_vector"][cat]["reviewer"]
            m = p["category_vector"][cat]["mlgg"]
            if r and m:
                tp += 1
            elif r and not m:
                fn += 1
            elif (not r) and m:
                fp += 1
            else:
                tn += 1
        sens = tp / (tp + fn) if (tp + fn) else None  # recall, mlgg vs reviewer
        spec = tn / (tn + fp) if (tn + fp) else None
        ppv = tp / (tp + fp) if (tp + fp) else None
        per_category[cat] = {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "n_papers_reviewer_flagged": tp + fn,
            "n_papers_mlgg_fired": tp + fp,
            "sensitivity": sens,
            "specificity": spec,
            "ppv": ppv,
        }

    # Per-rule cross-tab against reviewer categories
    # rows = R### rule, cols = (reviewer flagged that rule's category, not flagged)
    per_rule: dict[str, dict] = {}
    rule_universe: set[str] = set()
    for p in audited_with_gates:
        rule_universe.update(p["lint_rules_unique"])
    for rule in sorted(rule_universe):
        cats_for_rule = RULE_TO_CATEGORIES.get(rule, [])
        rev_flagged = 0  # papers where rule fired AND reviewer flagged ANY of rule's cats
        rev_not = 0
        n_papers_with_rule = 0
        for p in audited_with_gates:
            if rule not in p["lint_rules_unique"]:
                continue
            n_papers_with_rule += 1
            rev_cats = set(p["reviewer_categories"])
            if rev_cats.intersection(cats_for_rule):
                rev_flagged += 1
            else:
                rev_not += 1
        per_rule[rule] = {
            "categories": cats_for_rule,
            "n_papers_rule_fired": n_papers_with_rule,
            "n_papers_reviewer_aligned": rev_flagged,
            "n_papers_reviewer_not_aligned": rev_not,
        }

    # Overall recovery (restricted to audited_with_gates)
    total_reviewer_cat_hits = sum(
        sum(1 for cat in CATEGORIES if p["category_vector"][cat]["reviewer"])
        for p in audited_with_gates
    )
    total_overlap = sum(per_category[c]["tp"] for c in CATEGORIES)
    overall_recall = (
        total_overlap / total_reviewer_cat_hits
        if total_reviewer_cat_hits else None
    )
    total_mlgg_only = sum(per_category[c]["fp"] for c in CATEGORIES)
    additional_per_paper = (
        total_mlgg_only / n_audited_with_gates
        if n_audited_with_gates else None
    )

    # Lowest-overlap category among those with non-zero reviewer hits
    candidates = [
        (c, per_category[c]["sensitivity"])
        for c in CATEGORIES
        if per_category[c]["sensitivity"] is not None
    ]
    lowest = (
        min(candidates, key=lambda x: x[1])[0] if candidates else None
    )

    aggregate = {
        "n_trustable_papers": n_total,
        "n_audited_papers": n_audited,
        "n_unaudited_papers": n_total - n_audited,
        "n_audited_with_gates": n_audited_with_gates,
        "audited_paper_ids": [p["id"] for p in audited_papers],
        "unaudited_paper_ids": [
            p["id"] for p in per_paper if not p["audited"]
        ],
        "audited_with_gates_paper_ids": [
            p["id"] for p in audited_with_gates
        ],
        "papers_without_reviewer_gates": papers_without_gates,
        "categories": CATEGORIES,
        "per_category_confusion": per_category,
        "per_rule_alignment": per_rule,
        "overall": {
            "total_reviewer_category_hits": total_reviewer_cat_hits,
            "total_mlgg_overlap_hits": total_overlap,
            "overall_mlgg_recall": overall_recall,
            "total_mlgg_only_hits": total_mlgg_only,
            "mlgg_extra_categories_per_paper": additional_per_paper,
            "lowest_overlap_category": lowest,
        },
    }

    out = {
        "schema_version": 1,
        "generated_at_utc": _utc_now(),
        "category_scheme": CATEGORIES,
        "gate_to_category": GATE_TO_CATEGORIES,
        "rule_to_category": RULE_TO_CATEGORIES,
        "per_paper": per_paper,
        "aggregate": aggregate,
        "notes": [
            "trustable subset = cohort-binary scope AND reviewer_concerns "
            "non-empty AND peer_review_pdf_path non-empty",
            "audited = lint payload non-null (8 of the 13 cloned repos in "
            "lint-audit-results.json had non-null Python lint payloads); "
            "remaining 23 papers in trustable subset are awaiting Agent 2's "
            "lint-audit-110.json output",
            "confusion matrix is computed on the audited_with_gates subset: "
            "papers that have a lint payload AND at least one reviewer "
            "concern with mlgg_gates populated. Papers in the trustable "
            "subset with concerns but empty mlgg_gates (KB-curation gap) "
            "are listed under aggregate.papers_without_reviewer_gates.",
            "IP: per-paper records contain ID, gate names, rule IDs, "
            "category labels only; no concern text or paper title",
        ],
    }

    OUT_JSON.write_text(json.dumps(out, indent=2))

    # Build markdown
    md = build_md(out)
    OUT_MD.write_text(md)

    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    print()
    print("=== Summary ===")
    print(f"trustable papers:           {n_total}")
    print(f"audited (lint payload):     {n_audited}")
    print(f"  of which: have rev gates: {n_audited_with_gates}")
    print(f"  of which: no rev gates:   {n_audited - n_audited_with_gates}")
    print(f"unaudited (no payload):     {n_total - n_audited}")
    print(f"papers w/ concerns but no mlgg_gates: "
          f"{len(papers_without_gates)} ({', '.join(papers_without_gates)})")
    print()
    print("Per-category sensitivity (mlgg recall vs reviewer):")
    for cat in CATEGORIES:
        s = per_category[cat]["sensitivity"]
        s_str = f"{s:.2f}" if s is not None else "n/a"
        print(
            f"  {cat:<25}  TP={per_category[cat]['tp']}  "
            f"FN={per_category[cat]['fn']}  FP={per_category[cat]['fp']}  "
            f"TN={per_category[cat]['tn']}  sens={s_str}"
        )
    print()
    print(f"overall mlgg recall: {overall_recall}")
    print(f"mlgg-only categories per paper (extra issues): "
          f"{additional_per_paper}")
    print(f"lowest-overlap category: {lowest}")


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_md(out: dict) -> str:
    agg = out["aggregate"]
    cats = out["category_scheme"]
    pc = agg["per_category_confusion"]
    pr = agg["per_rule_alignment"]
    overall = agg["overall"]

    lines: list[str] = []
    lines.append("# Fig 4 confusion matrix data")
    lines.append("")
    lines.append(
        f"Trustable subset: **{agg['n_trustable_papers']}** papers "
        "(cohort-binary scope + reviewer_concerns + peer_review_pdf_path)"
    )
    lines.append(
        f"Audited so far: **{agg['n_audited_papers']}** papers "
        f"(lint payload available); "
        f"awaiting **{agg['n_unaudited_papers']}** from Agent 2"
    )
    lines.append(
        f"Confusion matrix is computed on the **{agg['n_audited_with_gates']}** "
        "papers that are both audited and have at least one reviewer concern "
        "with `mlgg_gates` populated."
    )
    lines.append("")
    lines.append("Audited paper IDs: " + ", ".join(agg["audited_paper_ids"]))
    lines.append(
        "Audited-with-gates paper IDs: "
        + ", ".join(agg["audited_with_gates_paper_ids"])
    )
    if agg["papers_without_reviewer_gates"]:
        lines.append(
            "KB-curation gap (concerns exist but `mlgg_gates` empty): "
            + ", ".join(agg["papers_without_reviewer_gates"])
        )
    lines.append("")
    lines.append("## (a) Per-category confusion matrix (paper-level)")
    lines.append("")
    lines.append(
        "| Category | TP | FN | FP | TN | "
        "Reviewer N | mlgg N | Sens | Spec | PPV |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for cat in cats:
        c = pc[cat]
        sens = f"{c['sensitivity']:.2f}" if c["sensitivity"] is not None else "n/a"
        spec = f"{c['specificity']:.2f}" if c["specificity"] is not None else "n/a"
        ppv = f"{c['ppv']:.2f}" if c["ppv"] is not None else "n/a"
        lines.append(
            f"| {cat} | {c['tp']} | {c['fn']} | {c['fp']} | {c['tn']} | "
            f"{c['n_papers_reviewer_flagged']} | "
            f"{c['n_papers_mlgg_fired']} | {sens} | {spec} | {ppv} |"
        )
    lines.append("")
    lines.append(
        "Definitions: TP = mlgg fired AND reviewer flagged the same "
        "category on the same paper; FN = reviewer flagged but mlgg "
        "did not; FP = mlgg fired but reviewer did not; "
        "TN = neither. Sensitivity = TP/(TP+FN) (mlgg recall vs "
        "reviewer); PPV = TP/(TP+FP)."
    )
    lines.append("")
    lines.append("## (b) Per-rule alignment with reviewer categories")
    lines.append("")
    lines.append(
        "| Rule | Categories | Papers fired | Reviewer aligned | Not aligned |"
    )
    lines.append("|---|---|---:|---:|---:|")
    for rule in sorted(pr.keys()):
        r = pr[rule]
        cats_str = ", ".join(r["categories"]) or "—"
        lines.append(
            f"| {rule} | {cats_str} | {r['n_papers_rule_fired']} | "
            f"{r['n_papers_reviewer_aligned']} | "
            f"{r['n_papers_reviewer_not_aligned']} |"
        )
    lines.append("")
    lines.append("## Overall")
    lines.append("")
    lines.append(
        f"- reviewer category-hits across audited papers: "
        f"{overall['total_reviewer_category_hits']}"
    )
    lines.append(
        f"- mlgg overlap (TP) hits: {overall['total_mlgg_overlap_hits']}"
    )
    rec = overall["overall_mlgg_recall"]
    rec_str = f"{rec:.2%}" if rec is not None else "n/a"
    lines.append(f"- overall mlgg recall vs reviewer: {rec_str}")
    extra = overall["mlgg_extra_categories_per_paper"]
    extra_str = f"{extra:.2f}" if extra is not None else "n/a"
    lines.append(
        f"- mlgg-flagged categories not in reviewer concerns "
        f"(extra issues per paper): {extra_str}"
    )
    lines.append(
        f"- lowest-sensitivity category: "
        f"{overall['lowest_overlap_category']}"
    )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
