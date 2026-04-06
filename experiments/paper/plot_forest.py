#!/usr/bin/env python3
"""
Generate forest plot and heatmap for the MLGG methods paper.

Produces:
  - Fig 2: Forest plot of AUC inflation (all_leaky vs clean)
  - Fig 5: Heatmap of per-leakage-type effect sizes across datasets

Usage:
  python3 experiments/paper/plot_forest.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
FIG_DIR = OUTPUT_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)


def load_data():
    with open(OUTPUT_DIR / "paired_tests.json") as f:
        paired = json.load(f)
    with open(OUTPUT_DIR / "forest_plot_data.json") as f:
        forest = json.load(f)
    return paired, forest


def fig2_forest_plot(forest: dict, paired: dict) -> None:
    """Forest plot: AUC inflation per dataset + pooled estimate."""
    entries = forest["entries"]
    pooled = forest["pooled_excluding_ceiling"]

    # Order: effect size descending, then pooled at bottom
    datasets_order = ["framingham", "diabetes130", "heart", "pima", "breast", "ckd"]
    labels = {
        "framingham": "Framingham (n=4,238)",
        "diabetes130": "Diabetes-130 (n=101,766)",
        "heart": "UCI Heart (n=297)",
        "pima": "Pima Indians (n=768)",
        "breast": "Breast Cancer (n=569)",
        "ckd": "Chronic Kidney (n=400)",
    }

    fig, ax = plt.subplots(figsize=(10, 5.5))

    y_positions = []
    y = len(datasets_order) + 1  # start from top

    entry_map = {e["dataset"]: e for e in entries}

    for ds in datasets_order:
        e = entry_map[ds]
        mean = e["mean"] * 100  # convert to percentage points
        ci_lo = e["ci_lower"] * 100
        ci_hi = e["ci_upper"] * 100

        is_ceiling = ds in ("ckd", "breast")
        color = "#999999" if is_ceiling else "#2166ac"
        marker = "D" if is_ceiling else "o"

        ax.errorbar(mean, y, xerr=[[mean - ci_lo], [ci_hi - mean]],
                    fmt=marker, color=color, capsize=4, markersize=8,
                    linewidth=1.5, markeredgewidth=1.5)

        # P-value annotation
        ds_data = paired["datasets"][ds]["all_leaky_vs_clean"]
        p = ds_data["wilcoxon_p_one_sided"] or ds_data["paired_t_p_one_sided"]
        sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else "ns"))
        ax.text(ci_hi + 0.15, y, f"  {sig}", va="center", fontsize=9, color=color)

        ax.text(-2.5, y, labels[ds], va="center", ha="right", fontsize=10,
                color="#333333" if not is_ceiling else "#999999")
        y_positions.append(y)
        y -= 1

    # Separator line
    ax.axhline(y=y + 0.5, color="#cccccc", linewidth=0.8, linestyle="--")

    # Pooled estimate (excluding ceiling)
    p_mean = pooled["pooled_estimate"] * 100
    p_lo = pooled["pooled_ci_95"][0] * 100
    p_hi = pooled["pooled_ci_95"][1] * 100

    ax.errorbar(p_mean, y, xerr=[[p_mean - p_lo], [p_hi - p_mean]],
                fmt="s", color="#b2182b", capsize=5, markersize=10,
                linewidth=2, markeredgewidth=2)
    ax.text(-2.5, y, f"Pooled (excl. ceiling)\nI²={pooled['I2_pct']:.0f}%, p={pooled['pooled_p']:.1e}",
            va="center", ha="right", fontsize=10, fontweight="bold", color="#b2182b")

    # Reference line at 0
    ax.axvline(x=0, color="#333333", linewidth=0.8, linestyle="-")

    ax.set_xlabel("AUC-ROC inflation (percentage points)", fontsize=11)
    ax.set_xlim(-3, 7)
    ax.set_ylim(y - 0.8, len(datasets_order) + 1.8)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Legend
    legend_elements = [
        mpatches.Patch(color="#2166ac", label="Informative datasets"),
        mpatches.Patch(color="#999999", label="Ceiling-effect datasets"),
        mpatches.Patch(color="#b2182b", label="Pooled (random-effects)"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=9, framealpha=0.9)

    ax.set_title("Figure 2. AUC-ROC inflation from data leakage (all_leaky vs clean pipeline)",
                 fontsize=12, fontweight="bold", pad=15)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig2_forest_plot.png", dpi=300, bbox_inches="tight")
    fig.savefig(FIG_DIR / "fig2_forest_plot.pdf", bbox_inches="tight")
    plt.close()
    print(f"Saved: {FIG_DIR / 'fig2_forest_plot.png'}")


def fig5_heatmap(paired: dict) -> None:
    """Heatmap: per-leakage-type effect sizes across datasets."""
    datasets = ["framingham", "diabetes130", "heart", "pima", "breast", "ckd"]
    ltypes = ["L1", "L2", "L3", "L4", "L5"]
    ltype_labels = [
        "L1: Preprocessing",
        "L2: Resampling",
        "L3: Feature selection",
        "L4: Patient grouping",
        "L5: Threshold optimization",
    ]
    ds_labels = [
        "Framingham", "Diabetes-130", "Heart", "Pima", "Breast", "CKD"
    ]

    # Build matrix
    matrix = np.zeros((len(ltypes), len(datasets)))
    for i, lt in enumerate(ltypes):
        lt_data = paired["per_leakage_type"].get(lt, {})
        for j, ds in enumerate(datasets):
            ds_data = lt_data.get(ds, {})
            matrix[i, j] = ds_data.get("mean_inflation", 0) * 100  # percentage points

    fig, ax = plt.subplots(figsize=(9, 5))

    # Custom diverging colormap
    im = ax.imshow(matrix, cmap="RdBu_r", aspect="auto", vmin=-3, vmax=7)

    # Annotations
    for i in range(len(ltypes)):
        for j in range(len(datasets)):
            val = matrix[i, j]
            color = "white" if abs(val) > 3 else "black"
            ax.text(j, i, f"{val:+.1f}", ha="center", va="center",
                    fontsize=10, color=color, fontweight="bold")

    ax.set_xticks(range(len(datasets)))
    ax.set_xticklabels(ds_labels, fontsize=10)
    ax.set_yticks(range(len(ltypes)))
    ax.set_yticklabels(ltype_labels, fontsize=10)

    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("AUC-ROC inflation (pp)", fontsize=10)

    ax.set_title("Figure 5. Per-leakage-type AUC inflation across datasets\n"
                 "(ablation_Lx vs clean; positive = inflation from leakage)",
                 fontsize=12, fontweight="bold", pad=15)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig5_heatmap.png", dpi=300, bbox_inches="tight")
    fig.savefig(FIG_DIR / "fig5_heatmap.pdf", bbox_inches="tight")
    plt.close()
    print(f"Saved: {FIG_DIR / 'fig5_heatmap.png'}")


def main() -> None:
    paired, forest = load_data()
    fig2_forest_plot(forest, paired)
    fig5_heatmap(paired)


if __name__ == "__main__":
    main()
