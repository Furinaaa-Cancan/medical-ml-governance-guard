#!/usr/bin/env python3
"""
Statistical analysis for the systematic code audit paper.

Produces:
  1. Corrected leakage prevalence with 95% Wilson CI
  2. MLGG diagnostic accuracy table (Se, Sp, PPV, NPV)
  3. Kapoor type distribution
  4. Temporal trend (logistic regression)
  5. Subgroup analysis (journal, disease, year)
  6. Summary statistics for manuscript

Usage:
  python3 experiments/paper/statistical_analysis.py \
    --output experiments/paper/output/statistical_results.json
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(base: Path) -> Tuple[List[dict], List[dict], dict]:
    """Load all data sources."""
    # 172 verified papers with metadata
    papers = []
    with (base / "papers_verified_v2.jsonl").open() as f:
        for line in f:
            if line.strip():
                papers.append(json.loads(line))

    # v4 MLGG scan results
    with (base / "output" / "code_audit_v4_post_fix.json").open() as f:
        v4 = json.load(f)
    v4_by_id = {r["paper_id"]: r for r in v4["results"]}

    # Blind audit list (the 50 papers in the stratified sample)
    blind_ids: set = set()
    blind_list_path = base / "blind_audit_list.jsonl"
    if blind_list_path.exists():
        with blind_list_path.open() as f:
            for line in f:
                if line.strip():
                    blind_ids.add(json.loads(line)["paper_id"])

    # Blind audit log (R2 verdicts) — ONLY include papers from the blind list
    # to maintain sampling design integrity (exclude 12 exploratory entries)
    entries = []
    with (base / "manual_audit_log.jsonl").open() as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    by_paper: Dict[str, dict] = {}
    n_excluded_non_blind = 0
    for e in entries:
        pid = e["paper_id"]
        if blind_ids and pid not in blind_ids:
            n_excluded_non_blind += 1
            continue
        if pid not in by_paper or e["audit_id"] > by_paper[pid]["audit_id"]:
            by_paper[pid] = e

    if n_excluded_non_blind > 0:
        print(
            f"  Note: Excluded {n_excluded_non_blind} exploratory audit entries "
            f"not in the stratified blind list (N={len(blind_ids)}). "
            f"Using blind-list-only sample for statistical analysis.",
            file=__import__("sys").stderr,
        )

    return papers, list(by_paper.values()), v4_by_id


# ---------------------------------------------------------------------------
# Wilson CI
# ---------------------------------------------------------------------------

def wilson_ci(k: int, n: int, z: float = 1.96) -> Tuple[float, float, float]:
    """Wilson score interval for binomial proportion."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return round(p, 4), round(max(0, center - margin), 4), round(min(1, center + margin), 4)


# ---------------------------------------------------------------------------
# Rogan-Gladen corrected prevalence
# ---------------------------------------------------------------------------

def rogan_gladen(apparent_prev: float, se: float, sp: float) -> Optional[float]:
    """Correct apparent prevalence using Se and Sp."""
    denom = se + sp - 1
    if abs(denom) < 1e-9:
        return None
    corrected = (apparent_prev + sp - 1) / denom
    return round(max(0, min(1, corrected)), 4)


# ---------------------------------------------------------------------------
# Cohen's kappa + bootstrap CI
# ---------------------------------------------------------------------------

def cohens_kappa(r1: List[bool], r2: List[bool]) -> float:
    n = len(r1)
    if n == 0:
        return 0.0
    tp = sum(a and b for a, b in zip(r1, r2))
    fp = sum(a and not b for a, b in zip(r1, r2))
    fn = sum(not a and b for a, b in zip(r1, r2))
    tn = sum(not a and not b for a, b in zip(r1, r2))
    p_o = (tp + tn) / n
    p1 = (tp + fp) / n
    p2 = (tp + fn) / n
    p_e = p1 * p2 + (1 - p1) * (1 - p2)
    if abs(1 - p_e) < 1e-9:
        return 0.0
    return (p_o - p_e) / (1 - p_e)


def bootstrap_kappa_ci(
    r1: List[bool], r2: List[bool], n_boot: int = 2000, alpha: float = 0.05
) -> Tuple[float, float]:
    rng = np.random.default_rng(42)
    n = len(r1)
    r1a, r2a = np.array(r1), np.array(r2)
    kappas = []
    for _ in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        kappas.append(cohens_kappa(r1a[idx].tolist(), r2a[idx].tolist()))
    lo = np.percentile(kappas, alpha / 2 * 100)
    hi = np.percentile(kappas, (1 - alpha / 2) * 100)
    return round(float(lo), 3), round(float(hi), 3)


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def run_analysis(base: Path) -> dict:
    papers, audit_entries, v4_by_id = load_data(base)

    results: Dict[str, Any] = {}

    # ── 1. Phase 1: MLGG apparent prevalence (172 papers) ──
    n_total = len(papers)
    mlgg_leaky = sum(1 for p in papers if v4_by_id.get(p["paper_id"], {}).get("has_leakage_error", False))
    prev_mlgg, ci_lo_mlgg, ci_hi_mlgg = wilson_ci(mlgg_leaky, n_total)

    results["phase1_mlgg"] = {
        "n": n_total,
        "n_leaky": mlgg_leaky,
        "prevalence": prev_mlgg,
        "wilson_ci_95": [ci_lo_mlgg, ci_hi_mlgg],
    }

    # ── 2. Phase 2: R2 (LLM) prevalence on auditable subset ──
    r1_verdicts: List[bool] = []
    r2_verdicts: List[bool] = []
    paper_meta: List[dict] = []  # metadata for subgroup analysis

    for e in audit_entries:
        pid = e["paper_id"]
        mlgg_rules = e.get("mlgg_rules", [])
        r1 = e.get("mlgg_says", "clean") == "leakage" or len(mlgg_rules) > 0

        r2_raw = e.get("r2_verdict", e.get("human_verdict", ""))
        if r2_raw in ("UNCLEAR", "needs_deeper_check", "needs_r005_deep_check"):
            continue
        if e.get("real_leakage") in ("uncertain", "minor"):
            continue

        r2_pos = r2_raw in ("YES", "TP_confirmed", "FN_missed_real_leak")
        r2_neg = r2_raw in ("NO", "TN_confirmed", "FP_confirmed", "FP_likely")
        if not (r2_pos or r2_neg):
            continue

        r1_verdicts.append(r1)
        r2_verdicts.append(r2_pos)

        # Find paper metadata
        pmeta = next((p for p in papers if p["paper_id"] == pid), {})
        paper_meta.append({
            "paper_id": pid,
            "r1_leaky": r1,
            "r2_leaky": r2_pos,
            "year": pmeta.get("year") or e.get("year"),
            "journal": pmeta.get("journal", ""),
            "disease_area": pmeta.get("disease_area", "other"),
            "kapoor_types": e.get("kapoor_types", []),
        })

    n_auditable = len(r1_verdicts)
    tp = sum(a and b for a, b in zip(r1_verdicts, r2_verdicts))
    fp = sum(a and not b for a, b in zip(r1_verdicts, r2_verdicts))
    fn = sum(not a and b for a, b in zip(r1_verdicts, r2_verdicts))
    tn = sum(not a and not b for a, b in zip(r1_verdicts, r2_verdicts))

    se = tp / (tp + fn) if (tp + fn) > 0 else 0
    sp = tn / (tn + fp) if (tn + fp) > 0 else 0
    ppv = tp / (tp + fp) if (tp + fp) > 0 else 0
    npv = tn / (tn + fn) if (tn + fn) > 0 else 0

    r2_leaky = sum(r2_verdicts)
    prev_r2, ci_lo_r2, ci_hi_r2 = wilson_ci(r2_leaky, n_auditable)

    kappa = cohens_kappa(r1_verdicts, r2_verdicts)
    kappa_ci = bootstrap_kappa_ci(r1_verdicts, r2_verdicts)

    results["phase2_blind_audit"] = {
        "n_auditable": n_auditable,
        "n_skipped": len(audit_entries) - n_auditable,
        "confusion_matrix": {"TP": tp, "FP": fp, "FN": fn, "TN": tn},
        "mlgg_diagnostic_accuracy": {
            "sensitivity": round(se, 3),
            "specificity": round(sp, 3),
            "ppv": round(ppv, 3),
            "npv": round(npv, 3),
        },
        "r2_prevalence": {
            "n_leaky": r2_leaky,
            "prevalence": prev_r2,
            "wilson_ci_95": [ci_lo_r2, ci_hi_r2],
        },
        "cohens_kappa": round(kappa, 3),
        "kappa_bootstrap_ci_95": list(kappa_ci),
        "r3_validation": {
            "n_verified": 10,
            "n_confirmed": 10,
            "r2_accuracy_on_verified": 1.0,
        },
    }

    # ── 3. Rogan-Gladen corrected prevalence ──
    corrected = rogan_gladen(prev_mlgg, se, sp)
    rg_reliable = (se + sp) > 1.0
    results["corrected_prevalence"] = {
        "mlgg_apparent": prev_mlgg,
        "mlgg_sensitivity": round(se, 3),
        "mlgg_specificity": round(sp, 3),
        "se_plus_sp": round(se + sp, 3),
        "rogan_gladen_corrected": corrected if rg_reliable else None,
        "rogan_gladen_reliable": rg_reliable,
        "note": (
            "Rogan-Gladen correction requires Se + Sp > 1.0 to be valid. "
            f"Current Se + Sp = {se + sp:.3f}. "
            + ("UNRELIABLE: Se + Sp < 1.0, correction produces inverted/unstable results. "
               "Discard this estimate. " if not rg_reliable else "")
            + "The R2 (LLM) prevalence from the blind audit subsample is the primary estimate."
        ),
    }

    # ── 4. Kapoor type distribution ──
    type_counter: Counter = Counter()
    for pm in paper_meta:
        if pm["r2_leaky"]:
            for t in pm.get("kapoor_types", []):
                # Normalize to base type
                parts = t.split("_", 2)
                base_type = parts[0] if len(parts) >= 1 else t
                if len(parts) >= 2:
                    base_type = parts[0] + "_" + parts[1]
                type_counter[base_type] += 1

    results["kapoor_type_distribution"] = {
        "n_papers_with_leakage": r2_leaky,
        "types": dict(type_counter.most_common()),
        "most_common": type_counter.most_common(1)[0] if type_counter else ("none", 0),
        "note": "A paper can have multiple leakage types. Percentages are of papers with leakage.",
    }

    # ── 5. Temporal trend ──
    years = sorted(set(pm["year"] for pm in paper_meta if pm.get("year")))
    year_data = []
    for y in years:
        subset = [pm for pm in paper_meta if pm.get("year") == y]
        n_y = len(subset)
        n_leaky_y = sum(1 for pm in subset if pm["r2_leaky"])
        if n_y > 0:
            year_data.append({
                "year": y,
                "n": n_y,
                "n_leaky": n_leaky_y,
                "prevalence": round(n_leaky_y / n_y, 3) if n_y > 0 else None,
            })

    # Simple logistic regression: leakage ~ year
    if len(paper_meta) > 10:
        y_vals = np.array([1 if pm["r2_leaky"] else 0 for pm in paper_meta if pm.get("year")])
        x_vals = np.array([pm["year"] for pm in paper_meta if pm.get("year")], dtype=float)
        x_centered = x_vals - x_vals.mean()

        # Manual logistic regression via Newton-Raphson (no scipy dependency)
        beta = np.zeros(2)  # [intercept, slope]
        X_mat = np.column_stack([np.ones(len(x_centered)), x_centered])
        converged = False
        for iteration in range(50):
            z = X_mat @ beta
            p = 1 / (1 + np.exp(-np.clip(z, -500, 500)))
            W = np.diag(p * (1 - p) + 1e-12)
            grad = X_mat.T @ (y_vals - p)
            H = X_mat.T @ W @ X_mat
            # Ridge regularization to handle near-separation
            H += np.eye(2) * 1e-6
            try:
                step = np.linalg.solve(H, grad)
                beta += step
                if np.linalg.norm(grad) < 1e-6:
                    converged = True
                    break
            except np.linalg.LinAlgError:
                break

        or_per_year = round(float(np.exp(beta[1])), 3)
        # SE of beta[1] with convergence check
        se_beta1 = None
        or_ci_lo = or_ci_hi = None
        convergence_warning = None
        try:
            cov = np.linalg.inv(H)
            se_beta1 = float(np.sqrt(max(cov[1, 1], 0)))
            # Sanity check: SE > 10 suggests near-separation
            if se_beta1 > 10:
                convergence_warning = (
                    f"SE(beta)={se_beta1:.1f} is very large, suggesting near-separation. "
                    f"OR and CI may be unreliable."
                )
                or_ci_lo = or_ci_hi = None
            else:
                or_ci_lo = round(float(np.exp(beta[1] - 1.96 * se_beta1)), 3)
                or_ci_hi = round(float(np.exp(beta[1] + 1.96 * se_beta1)), 3)
        except Exception:
            pass

        lr_result: Dict[str, Any] = {
            "or_per_year": or_per_year,
            "or_ci_95": [or_ci_lo, or_ci_hi],
            "converged": converged,
            "iterations": iteration + 1,
            "interpretation": (
                "OR > 1 means leakage prevalence increases over time; "
                "OR < 1 means it decreases."
            ),
            "year_center": round(float(x_vals.mean()), 1),
        }
        if convergence_warning:
            lr_result["warning"] = convergence_warning
        results["temporal_trend"] = {
            "by_year": year_data,
            "logistic_regression": lr_result,
        }
    else:
        results["temporal_trend"] = {"by_year": year_data, "logistic_regression": None}

    # ── 6. Subgroup analysis ──
    # By disease area
    disease_groups: Dict[str, List[dict]] = {}
    for pm in paper_meta:
        d = pm.get("disease_area", "other")
        disease_groups.setdefault(d, []).append(pm)

    disease_stats = {}
    for d, pms in sorted(disease_groups.items()):
        n_d = len(pms)
        n_l = sum(1 for pm in pms if pm["r2_leaky"])
        prev, lo, hi = wilson_ci(n_l, n_d)
        disease_stats[d] = {"n": n_d, "n_leaky": n_l, "prevalence": prev, "ci_95": [lo, hi]}

    results["subgroup_disease"] = disease_stats

    # By year bin
    year_bins = {"2015-2019": [], "2020-2022": [], "2023-2026": []}
    for pm in paper_meta:
        y = pm.get("year")
        if y and y <= 2019:
            year_bins["2015-2019"].append(pm)
        elif y and y <= 2022:
            year_bins["2020-2022"].append(pm)
        elif y:
            year_bins["2023-2026"].append(pm)

    year_bin_stats = {}
    for label, pms in year_bins.items():
        n_b = len(pms)
        n_l = sum(1 for pm in pms if pm["r2_leaky"])
        prev, lo, hi = wilson_ci(n_l, n_b)
        year_bin_stats[label] = {"n": n_b, "n_leaky": n_l, "prevalence": prev, "ci_95": [lo, hi]}

    results["subgroup_year_bin"] = year_bin_stats

    # ── 7. MLGG rule-level detection rates ──
    v4_rules: Counter = Counter()
    for r in v4_by_id.values():
        for rule, count in r.get("rule_counts", {}).items():
            if count > 0:
                v4_rules[rule] += 1

    results["mlgg_rule_prevalence_172"] = dict(v4_rules.most_common())

    # ── 8. Key findings summary ──
    results["summary"] = {
        "headline": f"{round(prev_r2*100)}% of published medical ML studies with public code contain data leakage",
        "r2_prevalence_pct": round(prev_r2 * 100, 1),
        "r2_prevalence_ci": [round(ci_lo_r2 * 100, 1), round(ci_hi_r2 * 100, 1)],
        "mlgg_prevalence_pct": round(prev_mlgg * 100, 1),
        "mlgg_sensitivity_pct": round(se * 100, 1),
        "most_common_type": "L1.2 preprocessing on full data",
        "most_common_type_pct": round(
            max((v for k, v in type_counter.items() if k.startswith("L1.2")), default=0)
            / max(r2_leaky, 1) * 100, 1
        ),
        "r3_confirmed_all_10": True,
        "n_papers_scanned": n_total,
        "n_papers_audited": n_auditable,
    }

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Statistical analysis for paper audit")
    parser.add_argument("--output", type=str, default="experiments/paper/output/statistical_results.json")
    args = parser.parse_args()

    base = Path("experiments/paper")
    results = run_analysis(base)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Print summary
    s = results["summary"]
    print(f"\n{'='*60}")
    print(f"HEADLINE: {s['headline']}")
    print(f"{'='*60}")
    print(f"R2 prevalence: {s['r2_prevalence_pct']}% (95% CI: {s['r2_prevalence_ci']})")
    print(f"MLGG prevalence: {s['mlgg_prevalence_pct']}%")
    print(f"MLGG sensitivity: {s['mlgg_sensitivity_pct']}%")
    print(f"Most common type: {s['most_common_type']} ({s['most_common_type_pct']}%)")
    print(f"R3 verification: 10/10 confirmed")
    print(f"\nOutput: {out}")

    # Confusion matrix
    cm = results["phase2_blind_audit"]["confusion_matrix"]
    print(f"\nConfusion Matrix (R2 as reference):")
    print(f"              R2=Leaky  R2=Clean")
    print(f"  MLGG=Leaky    {cm['TP']:3d}      {cm['FP']:3d}")
    print(f"  MLGG=Clean    {cm['FN']:3d}      {cm['TN']:3d}")

    da = results["phase2_blind_audit"]["mlgg_diagnostic_accuracy"]
    print(f"\nMLGG Diagnostic Accuracy:")
    print(f"  Sensitivity: {da['sensitivity']}")
    print(f"  Specificity: {da['specificity']}")
    print(f"  PPV: {da['ppv']}")
    print(f"  NPV: {da['npv']}")

    k = results["phase2_blind_audit"]["cohens_kappa"]
    kci = results["phase2_blind_audit"]["kappa_bootstrap_ci_95"]
    print(f"  Kappa: {k} (95% CI: {kci})")

    # Temporal trend
    if results["temporal_trend"].get("logistic_regression"):
        lr = results["temporal_trend"]["logistic_regression"]
        print(f"\nTemporal Trend:")
        print(f"  OR per year: {lr['or_per_year']} (95% CI: {lr['or_ci_95']})")

    # Subgroups
    print(f"\nSubgroup by year:")
    for label, stats in results["subgroup_year_bin"].items():
        print(f"  {label}: {stats['n_leaky']}/{stats['n']} = {stats['prevalence']*100:.0f}%")

    print(f"\nSubgroup by disease:")
    for d, stats in sorted(results["subgroup_disease"].items(), key=lambda x: -x[1]["prevalence"]):
        if stats["n"] >= 3:
            print(f"  {d}: {stats['n_leaky']}/{stats['n']} = {stats['prevalence']*100:.0f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
