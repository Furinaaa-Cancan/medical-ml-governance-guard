#!/usr/bin/env python3
"""
Paired statistical tests for the deflation experiment.

For each dataset, pairs all_leaky vs clean by seed and runs:
  - Paired Wilcoxon signed-rank test (non-parametric)
  - Paired t-test (parametric)
  - Per-leakage-type ablation effect (each ablation_Lx vs clean)
  - Brier score inflation analysis
  - Forest plot data (pooled random-effects meta-analysis)

Outputs:
  - experiments/paper/output/paired_tests.json
  - experiments/paper/output/forest_plot_data.json
  - Console summary table

Usage:
  python3 experiments/paper/statistical_tests_deflation.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
CSV_PATH = OUTPUT_DIR / "deflation_summary.csv"

DATASETS_ORDER = ["framingham", "diabetes130", "heart", "pima", "breast", "ckd"]
CONDITIONS_LEAKY = ["all_leaky", "ablation_L1", "ablation_L2", "ablation_L3",
                    "ablation_L4", "ablation_L5"]
LEAKAGE_LABELS = {
    "all_leaky": "All 5 leakage types",
    "ablation_L1": "All except preprocessing (L1 corrected)",
    "ablation_L2": "All except resampling (L2 corrected)",
    "ablation_L3": "All except feature selection (L3 corrected)",
    "ablation_L4": "All except patient grouping (L4 corrected)",
    "ablation_L5": "All except threshold (L5 corrected)",
}


def paired_test(leaky_vals: np.ndarray, clean_vals: np.ndarray) -> dict:
    """Run paired Wilcoxon and paired t-test, return results dict."""
    diffs = leaky_vals - clean_vals
    n = len(diffs)
    mean_diff = float(np.mean(diffs))
    std_diff = float(np.std(diffs, ddof=1))
    se_diff = std_diff / np.sqrt(n) if n > 1 else float("nan")

    # Paired t-test
    t_stat, t_p = stats.ttest_rel(leaky_vals, clean_vals)

    # Wilcoxon signed-rank (requires non-zero diffs)
    nonzero_diffs = diffs[diffs != 0]
    if len(nonzero_diffs) >= 6:  # minimum for meaningful Wilcoxon
        w_stat, w_p = stats.wilcoxon(nonzero_diffs, alternative="greater")
    else:
        w_stat, w_p = float("nan"), float("nan")

    # Effect size: Cohen's d for paired samples
    cohens_d = mean_diff / std_diff if std_diff > 0 else float("nan")

    # 95% CI for mean difference
    if n > 1:
        t_crit = stats.t.ppf(0.975, df=n - 1)
        ci_lower = mean_diff - t_crit * se_diff
        ci_upper = mean_diff + t_crit * se_diff
    else:
        ci_lower = ci_upper = float("nan")

    return {
        "n_seeds": int(n),
        "mean_inflation": round(mean_diff, 6),
        "std_inflation": round(std_diff, 6),
        "se_inflation": round(se_diff, 6),
        "ci_95_lower": round(ci_lower, 6),
        "ci_95_upper": round(ci_upper, 6),
        "cohens_d": round(cohens_d, 4),
        "paired_t_stat": round(float(t_stat), 4),
        "paired_t_p": round(float(t_p), 6),
        "paired_t_p_one_sided": round(float(t_p) / 2 if t_stat > 0 else 1.0 - float(t_p) / 2, 6),
        "wilcoxon_stat": round(float(w_stat), 4) if not np.isnan(w_stat) else None,
        "wilcoxon_p_one_sided": round(float(w_p), 6) if not np.isnan(w_p) else None,
        "leaky_mean": round(float(np.mean(leaky_vals)), 6),
        "clean_mean": round(float(np.mean(clean_vals)), 6),
    }


def pooled_meta_analysis(effects: list[dict]) -> dict:
    """
    Random-effects meta-analysis (DerSimonian-Laird) across datasets.
    Each entry needs: mean_inflation, se_inflation.
    """
    # Accept both key names
    def _se(e: dict) -> float:
        return e.get("se_inflation", e.get("se", 0.0))
    def _mean(e: dict) -> float:
        return e.get("mean_inflation", e.get("mean", 0.0))

    valid = [e for e in effects if _se(e) > 0 and not np.isnan(_se(e))]
    if len(valid) < 2:
        return {"pooled_estimate": None, "note": "insufficient data"}

    ys = np.array([_mean(e) for e in valid])
    ses = np.array([_se(e) for e in valid])
    ws_fe = 1.0 / (ses ** 2)

    # Fixed-effect estimate
    mu_fe = np.sum(ws_fe * ys) / np.sum(ws_fe)

    # Cochran's Q
    Q = np.sum(ws_fe * (ys - mu_fe) ** 2)
    k = len(valid)
    df = k - 1

    # DerSimonian-Laird tau^2
    c = np.sum(ws_fe) - np.sum(ws_fe ** 2) / np.sum(ws_fe)
    tau2 = max(0.0, (Q - df) / c)

    # Random-effects weights
    ws_re = 1.0 / (ses ** 2 + tau2)
    mu_re = np.sum(ws_re * ys) / np.sum(ws_re)
    se_re = 1.0 / np.sqrt(np.sum(ws_re))

    z_crit = 1.96
    ci_lower = mu_re - z_crit * se_re
    ci_upper = mu_re + z_crit * se_re

    # Heterogeneity
    I2 = max(0.0, (Q - df) / Q * 100) if Q > 0 else 0.0
    Q_p = float(stats.chi2.sf(Q, df))

    return {
        "k_datasets": k,
        "pooled_estimate": round(float(mu_re), 6),
        "pooled_se": round(float(se_re), 6),
        "pooled_ci_95": [round(float(ci_lower), 6), round(float(ci_upper), 6)],
        "pooled_z": round(float(mu_re / se_re), 4),
        "pooled_p": round(float(2 * stats.norm.sf(abs(mu_re / se_re))), 8),
        "tau2": round(float(tau2), 8),
        "I2_pct": round(float(I2), 1),
        "cochrans_Q": round(float(Q), 4),
        "Q_p": round(float(Q_p), 6),
        "heterogeneity": "low" if I2 < 25 else ("moderate" if I2 < 75 else "high"),
    }


def main() -> None:
    df = pd.read_csv(CSV_PATH)
    results: dict = {"datasets": {}, "per_leakage_type": {}, "brier_analysis": {}}

    # ── 1. Per-dataset: all_leaky vs clean ──
    print("\n" + "=" * 80)
    print("PAIRED TESTS: all_leaky vs clean (AUC-ROC)")
    print("=" * 80)
    print(f"{'Dataset':<14} {'N':>4} {'Clean':>7} {'Leaky':>7} {'Δ AUC':>8} "
          f"{'Δ%':>6} {'d':>6} {'t-p':>10} {'W-p':>10} {'Sig':>4}")
    print("-" * 80)

    forest_entries = []

    for ds in DATASETS_ORDER:
        sub = df[df["dataset"] == ds]
        clean = sub[sub["condition"] == "clean"].set_index("seed")["test_auc_roc"]
        leaky = sub[sub["condition"] == "all_leaky"].set_index("seed")["test_auc_roc"]
        seeds = sorted(set(clean.index) & set(leaky.index))
        c_vals = clean.loc[seeds].values
        l_vals = leaky.loc[seeds].values

        res = paired_test(l_vals, c_vals)
        results["datasets"][ds] = {"all_leaky_vs_clean": res}

        # Significance marker
        p = res["wilcoxon_p_one_sided"] or res["paired_t_p_one_sided"]
        sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else "ns"))
        pct = res["mean_inflation"] / res["clean_mean"] * 100 if res["clean_mean"] > 0 else 0

        print(f"{ds:<14} {res['n_seeds']:>4} {res['clean_mean']:>7.4f} {res['leaky_mean']:>7.4f} "
              f"{res['mean_inflation']:>+8.4f} {pct:>+5.1f}% {res['cohens_d']:>6.2f} "
              f"{res['paired_t_p_one_sided']:>10.6f} "
              f"{res['wilcoxon_p_one_sided'] if res['wilcoxon_p_one_sided'] else 'N/A':>10} {sig:>4}")

        forest_entries.append({
            "dataset": ds,
            "condition": "all_leaky_vs_clean",
            "mean": res["mean_inflation"],
            "ci_lower": res["ci_95_lower"],
            "ci_upper": res["ci_95_upper"],
            "se": res["se_inflation"],
            "weight": 1.0 / (res["se_inflation"] ** 2) if res["se_inflation"] > 0 else 0,
            "n_seeds": res["n_seeds"],
            "cohens_d": res["cohens_d"],
            "p_value": p,
        })

    # ── 2. Per-leakage-type across datasets ──
    print("\n" + "=" * 80)
    print("PER-LEAKAGE-TYPE ANALYSIS (ablation_Lx vs clean)")
    print("=" * 80)

    for cond in CONDITIONS_LEAKY:
        if cond == "all_leaky":
            continue
        ltype = cond.replace("ablation_", "")
        results["per_leakage_type"][ltype] = {}

        print(f"\n── {cond}: {LEAKAGE_LABELS[cond]} ──")
        print(f"{'Dataset':<14} {'Δ AUC':>8} {'Δ%':>6} {'d':>6} {'W-p':>10}")

        type_forest = []
        for ds in DATASETS_ORDER:
            sub = df[df["dataset"] == ds]
            clean = sub[sub["condition"] == "clean"].set_index("seed")["test_auc_roc"]
            ablation = sub[sub["condition"] == cond].set_index("seed")["test_auc_roc"]
            seeds = sorted(set(clean.index) & set(ablation.index))
            if not seeds:
                continue
            c_vals = clean.loc[seeds].values
            a_vals = ablation.loc[seeds].values
            res = paired_test(a_vals, c_vals)
            results["per_leakage_type"][ltype][ds] = res

            pct = res["mean_inflation"] / res["clean_mean"] * 100 if res["clean_mean"] > 0 else 0
            wp = res["wilcoxon_p_one_sided"]
            print(f"{ds:<14} {res['mean_inflation']:>+8.4f} {pct:>+5.1f}% {res['cohens_d']:>6.2f} "
                  f"{wp if wp else 'N/A':>10}")

            type_forest.append({
                "dataset": ds,
                "mean_inflation": res["mean_inflation"],
                "se_inflation": res["se_inflation"],
            })

        # Pool across datasets for this leakage type
        pooled = pooled_meta_analysis(type_forest)
        results["per_leakage_type"][ltype]["_pooled"] = pooled
        if pooled["pooled_estimate"] is not None:
            print(f"{'POOLED':<14} {pooled['pooled_estimate']:>+8.4f} "
                  f"       {'':>6} {'':>10} "
                  f"(I²={pooled['I2_pct']:.0f}%, p={pooled['pooled_p']:.6f})")

    # ── 3. Brier score analysis ──
    print("\n" + "=" * 80)
    print("BRIER SCORE INFLATION (all_leaky vs clean)")
    print("=" * 80)
    print(f"{'Dataset':<14} {'Clean':>8} {'Leaky':>8} {'Δ Brier':>9} {'d':>6} {'W-p':>10}")
    print("-" * 70)

    for ds in DATASETS_ORDER:
        sub = df[df["dataset"] == ds]
        clean = sub[sub["condition"] == "clean"].set_index("seed")["test_brier"]
        leaky = sub[sub["condition"] == "all_leaky"].set_index("seed")["test_brier"]
        seeds = sorted(set(clean.index) & set(leaky.index))
        c_vals = clean.loc[seeds].values
        l_vals = leaky.loc[seeds].values
        # For Brier, lower is better, so leaky < clean means artificial improvement
        res = paired_test(c_vals, l_vals)  # reversed: clean - leaky = improvement from leakage
        results["brier_analysis"][ds] = {
            "clean_mean_brier": round(float(np.mean(c_vals)), 6),
            "leaky_mean_brier": round(float(np.mean(l_vals)), 6),
            "brier_reduction": res["mean_inflation"],  # how much leakage "improves" Brier
            "cohens_d": res["cohens_d"],
            "wilcoxon_p": res["wilcoxon_p_one_sided"],
            "paired_t_p": res["paired_t_p_one_sided"],
        }
        wp = results["brier_analysis"][ds]["wilcoxon_p"]
        print(f"{ds:<14} {np.mean(c_vals):>8.4f} {np.mean(l_vals):>8.4f} "
              f"{res['mean_inflation']:>+9.4f} {res['cohens_d']:>6.2f} "
              f"{wp if wp else 'N/A':>10}")

    # ── 4. Train-test gap analysis ──
    print("\n" + "=" * 80)
    print("TRAIN-TEST GAP (all_leaky vs clean)")
    print("=" * 80)
    print(f"{'Dataset':<14} {'Clean Gap':>10} {'Leaky Gap':>10} {'Δ Gap':>8}")
    print("-" * 50)

    for ds in DATASETS_ORDER:
        sub = df[df["dataset"] == ds]
        clean = sub[sub["condition"] == "clean"].set_index("seed")["train_test_gap"]
        leaky = sub[sub["condition"] == "all_leaky"].set_index("seed")["train_test_gap"]
        seeds = sorted(set(clean.index) & set(leaky.index))
        c_gap = clean.loc[seeds].values.mean()
        l_gap = leaky.loc[seeds].values.mean()
        results["datasets"][ds]["train_test_gap"] = {
            "clean_mean_gap": round(float(c_gap), 6),
            "leaky_mean_gap": round(float(l_gap), 6),
            "gap_increase": round(float(l_gap - c_gap), 6),
        }
        print(f"{ds:<14} {c_gap:>10.4f} {l_gap:>10.4f} {l_gap - c_gap:>+8.4f}")

    # ── 5. Meta-analysis (forest plot) ──
    print("\n" + "=" * 80)
    print("RANDOM-EFFECTS META-ANALYSIS: all_leaky vs clean")
    print("=" * 80)

    # All 6 datasets
    pooled_all = pooled_meta_analysis(forest_entries)
    results["meta_analysis"] = {"all_6_datasets": pooled_all}
    print(f"All 6 datasets:  pooled Δ = {pooled_all['pooled_estimate']:+.4f} "
          f"(95% CI: {pooled_all['pooled_ci_95'][0]:+.4f} to {pooled_all['pooled_ci_95'][1]:+.4f}), "
          f"p = {pooled_all['pooled_p']:.8f}, I² = {pooled_all['I2_pct']:.0f}%")

    # Excluding ceiling-effect datasets (ckd, breast)
    non_ceiling = [e for e in forest_entries if e["dataset"] not in ("ckd", "breast")]
    pooled_nc = pooled_meta_analysis(non_ceiling)
    results["meta_analysis"]["excluding_ceiling"] = pooled_nc
    print(f"Excl. ceiling:   pooled Δ = {pooled_nc['pooled_estimate']:+.4f} "
          f"(95% CI: {pooled_nc['pooled_ci_95'][0]:+.4f} to {pooled_nc['pooled_ci_95'][1]:+.4f}), "
          f"p = {pooled_nc['pooled_p']:.8f}, I² = {pooled_nc['I2_pct']:.0f}%")

    # ── 6. Save ──
    forest_data = {
        "entries": forest_entries,
        "pooled_all": pooled_all,
        "pooled_excluding_ceiling": pooled_nc,
    }

    with open(OUTPUT_DIR / "paired_tests.json", "w") as f:
        json.dump(results, f, indent=2)
    with open(OUTPUT_DIR / "forest_plot_data.json", "w") as f:
        json.dump(forest_data, f, indent=2)

    print(f"\nSaved: {OUTPUT_DIR / 'paired_tests.json'}")
    print(f"Saved: {OUTPUT_DIR / 'forest_plot_data.json'}")


if __name__ == "__main__":
    main()
