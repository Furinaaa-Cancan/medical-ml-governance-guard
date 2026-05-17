"""Render Fig 1 / Fig 2 / Fig 3 for the mlgg paper (outline v0.3 Result section).

Fig 1: Lint corpus prevalence — horizontal bar chart of how many of the 92
       cohort-binary repos triggered each rule. Source: paper/lint-audit-110.json.

Fig 2: A3 stratified TP/FP per rule — bar chart of TP vs FP counts per rule
       from the n=50 manual review. Source: /tmp/agent03-tpfp-sample.json
       (preserved in repo at paper/raw-extraction-artifacts/ if available).

Fig 3: Rule revision impact (B8 + B9) — before vs after precision on the
       FP cases identified by A3 for R021/R008/R004.

Run: python3 scripts/diagnostics/render_paper_figures.py
Output: paper/figures/{fig1,fig2,fig3}.{png,pdf}
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
FIG_DIR = ROOT / "paper" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

LINT_PATH = ROOT / "paper" / "lint-audit-110.json"


def _save_fig(fig, name: str) -> None:
    """Save figure to both PNG (300 dpi) and PDF (vector)."""
    fig.savefig(FIG_DIR / f"{name}.png", dpi=300, bbox_inches="tight")
    fig.savefig(FIG_DIR / f"{name}.pdf", bbox_inches="tight")
    print(f"  → {FIG_DIR / name}.png + .pdf")


def render_fig1_lint_prevalence() -> None:
    """Horizontal bar: per-rule paper count (top 15) from A2's audit."""
    d = json.loads(LINT_PATH.read_text())
    # rules_fired_across_corpus is {rule_id: paper_count}; rules_total_findings is {rule_id: total_findings}
    paper_count = d.get("rules_fired_across_corpus", {})
    total_findings = d.get("rules_total_findings", {})

    # Top 15 by paper count
    items = sorted(paper_count.items(), key=lambda x: -x[1])[:15]
    rules = [k for k, _ in items][::-1]  # reverse for horizontal bar (top at top)
    papers = [paper_count[r] for r in rules]
    findings = [total_findings.get(r, 0) for r in rules]

    n_total_papers = d.get("stats", {}).get("repos_with_findings", 48)

    fig, ax = plt.subplots(figsize=(7.5, 6))
    y = list(range(len(rules)))
    ax.barh(y, papers, color="#1f77b4", height=0.55, label=f"Papers (n={n_total_papers} with ≥1 finding)")
    # Overlay total finding count as text annotation
    for i, (p, f) in enumerate(zip(papers, findings)):
        ax.text(p + 0.3, i, f"  {p}p / {f}f", va="center", fontsize=8, color="#555")

    ax.set_yticks(y)
    ax.set_yticklabels(rules, fontsize=10)
    ax.set_xlabel("Number of papers triggering rule")
    ax.set_title("Fig 1. Lint corpus prevalence — mlgg-lint AST rule hits across\n"
                 f"92 cohort-binary peer-review-linked GitHub repos ({n_total_papers}/92 with ≥1 finding, 448 findings total)",
                 fontsize=11)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlim(0, max(papers) * 1.25)
    ax.set_axisbelow(True)
    ax.grid(axis="x", linestyle="--", alpha=0.3)

    _save_fig(fig, "fig1_lint_prevalence")
    plt.close(fig)


def render_fig2_a3_tpfp() -> None:
    """Stacked bar: per-rule TP vs FP from A3's stratified review (n=50)."""
    # Try repo-persisted artifact first, fall back to /tmp/
    candidates = [
        ROOT / "paper" / "raw-extraction-artifacts" / "agent03-tpfp-sample.json",
        Path("/tmp/agent03-tpfp-sample.json"),
    ]
    a3_path = next((p for p in candidates if p.exists()), None)
    if a3_path is None:
        raise FileNotFoundError(f"A3 TP/FP sample not found in any of: {candidates}")
    d = json.loads(a3_path.read_text())
    by_rule = d["aggregate"]["by_rule"]
    # Sort by total sample size (TP+FP+unclear), keep all
    rules = sorted(
        by_rule.keys(),
        key=lambda r: -(by_rule[r]["TP"] + by_rule[r]["FP"] + by_rule[r].get("unclear", 0)),
    )
    tp = [by_rule[r]["TP"] for r in rules]
    fp = [by_rule[r]["FP"] for r in rules]

    total_tp = d["aggregate"]["TP"]
    total_fp = d["aggregate"]["FP"]
    tp_rate = d["aggregate"]["TP_rate"]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    x = list(range(len(rules)))
    ax.bar(x, tp, color="#2ca02c", label=f"True Positive (n={total_tp})")
    ax.bar(x, fp, bottom=tp, color="#d62728", label=f"False Positive (n={total_fp})")

    # Annotate FP rules
    for i, r in enumerate(rules):
        total = tp[i] + fp[i]
        if total > 0:
            pct = tp[i] / total * 100
            label = f"{pct:.0f}%" if total >= 3 else ""  # only annotate where sample ≥3
            color = "darkred" if pct < 50 else "black"
            ax.text(i, total + 0.1, label, ha="center", fontsize=9, fontweight="bold", color=color)

    ax.set_xticks(x)
    ax.set_xticklabels(rules, fontsize=10)
    ax.set_xlabel("mlgg-lint rule")
    ax.set_ylabel("Number of findings (stratified random sample)")
    ax.set_title(f"Fig 2. Manual TP/FP review on stratified random sample of mlgg-lint findings\n"
                 f"(n=50, 8-per-rule cap, seed=42; aggregate TP rate {tp_rate*100:.0f}%)",
                 fontsize=11)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_axisbelow(True)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.legend(loc="upper right", frameon=False)

    # Footer call-out for revised rules
    fig.text(0.5, -0.02,
             "Rules with <50% TP rate (R021, R008, R004) were revised in this work; see Fig 3.",
             ha="center", fontsize=9, style="italic", color="#555")

    _save_fig(fig, "fig2_a3_tpfp")
    plt.close(fig)


def render_fig3_revision_impact() -> None:
    """Side-by-side before/after FP suppression for the 3 revised rules.

    Numbers come from the 10-agent wave summaries:
      - R021 (B8): 4 PR-086 FPs → 4 suppressed → 0 remaining FP.
                   TP cases (synthetic grid/set_params/attr-assign) preserved.
      - R008 (B9): 2 A3 FPs → 1 suppressed (finding_id 42).
                   finding_id 22 (3D LSTM with mRS binary) still fires per
                   spec; flagged as spec/A3 disagreement.
      - R004 (B9): 3 A3 FPs → 3 suppressed (finding_id 39/54/56).
                   2 TPs preserved (finding_id 7 longitudinal, 82 raw values).
    """
    rules = ["R021", "R008", "R004"]
    fp_before = [4, 2, 3]
    fp_after = [0, 1, 0]
    tp_preserved = [3, 1, 2]  # synthetic / fixture TPs that still fire

    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    x = list(range(len(rules)))
    width = 0.32

    bars_before = ax.bar([i - width for i in x], fp_before, width, color="#d62728",
                         label="FP before revision")
    bars_after = ax.bar([i for i in x], fp_after, width, color="#ff9896",
                        label="FP after revision")
    bars_tp = ax.bar([i + width for i in x], tp_preserved, width, color="#2ca02c",
                     label="TP preserved")

    for bars in (bars_before, bars_after, bars_tp):
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h + 0.05, f"{int(h)}",
                    ha="center", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(rules, fontsize=11)
    ax.set_xlabel("Revised mlgg-lint rule")
    ax.set_ylabel("Findings count")
    ax.set_title("Fig 3. AST rule revisions reduce false positives without losing\n"
                 "true positives — three rules with <50% precision in Fig 2 were\n"
                 "revised based on the failure-mode analysis from manual review",
                 fontsize=11)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(loc="upper right", frameon=False)
    ax.set_ylim(0, max(max(fp_before), max(tp_preserved)) + 1.5)
    ax.set_axisbelow(True)
    ax.grid(axis="y", linestyle="--", alpha=0.3)

    fig.text(0.5, -0.02,
             "R008 retains 1 FP at finding_id 22 (3D LSTM input shape with mRS binary task) — "
             "flagged for follow-up.",
             ha="center", fontsize=8, style="italic", color="#555")

    _save_fig(fig, "fig3_revision_impact")
    plt.close(fig)


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    print("Rendering paper figures →", FIG_DIR)
    print()
    print("Fig 1: lint corpus prevalence")
    render_fig1_lint_prevalence()
    print()
    print("Fig 2: A3 TP/FP stratified review")
    render_fig2_a3_tpfp()
    print()
    print("Fig 3: rule revision impact")
    render_fig3_revision_impact()
    print()
    print("Done.")


if __name__ == "__main__":
    main()
