# KB Curation Proposal — `prediction_replay_gate` + `robustness_gate`

**Author**: Agent F4 (parallel fix-wave on MLGG RAG)
**Date**: 2026-05-16
**Target file**: `references/case-studies/peer-review-kb.json` (contract `peer_review_kb.v1.4`)
**Status**: PROPOSAL ONLY — no KB writes performed (CLAUDE.md rule §68: "不自行写入 `references/*.json`").

---

## Context

Per the 5-agent strict eval (E5), these two gates have weak peer-review precedent in the current KB:

| Gate | Concerns in KB | Top-1 RAG score | Issue |
|---|---|---|---|
| `prediction_replay_gate` | 1 (PR-113-C03) | 0.033 | Only tagged concern is about prospective validation, not replay determinism. Effectively zero useful coverage. |
| `robustness_gate` | 7 | 0.368 | Top hit (PR-012-C04) is tangential (outlier sensitivity); subgroup-stability / temporal-drift / scanner-variance reviewer patterns are not surfaced. |

**Goal**: bring each gate to ≥5 strong concerns. P@5 expected to improve from ~0 → ≥0.6 after curation.

**Method preference**: re-tag existing concerns whenever possible. New synthetic concerns are NOT proposed in this iteration because re-tagging alone exceeds the target for both gates.

---

## Proposal A — Re-tagging existing concerns

### A.1 `prediction_replay_gate` (target: +5–10; proposing **+8**)

The gate as defined in MLGG checks that re-running the prediction pipeline yields identical / bounded-variance outputs. Reviewer patterns that map to this gate include: (a) inability to re-execute the pipeline at all (broken code/install, missing methods detail), (b) unspecified random seeds / no variance reporting, (c) missing tool versions / pipeline version drift, (d) missing audit trail of how predictions were produced.

The KB already has 20 concerns whose `tags` list contains a `reproducibility*` / `irreproducible_methods` token but does NOT include `prediction_replay_gate` in `mlgg_gates`. The 8 strongest are below.

| # | concern_id | current `mlgg_gates` | suggested addition | justification (concern_text snippet) |
|---|---|---|---|---|
| 1 | `PR-EXP-0200-C04` | `evaluation_quality_gate`, `ci_matrix_gate`, `seed_stability_gate` | + `prediction_replay_gate` | "It is standard practice to go train a network several times to determine the influence of the random seed used for training. Without such information, it is impossible to tell if the results are spurious or not." — Canonical seed-variance / replay concern. Without seed variance, you cannot know whether re-running gives the same prediction. |
| 2 | `PR-EXP-0119-C09` | `publication_gate`, `seed_stability_gate`, `execution_attestation_gate` | + `prediction_replay_gate` | "We attempted to run the code provided in the GitHub repository but encountered some issues during the installation and in the demo.py file." — Direct replay failure: reviewer literally could not re-execute the pipeline. |
| 3 | `PR-EXP-0084-C04` | `model_selection_audit_gate`, `tuning_leakage_gate`, `seed_stability_gate`, `execution_attestation_gate` | + `prediction_replay_gate` | "There is a lack of detail in the description of the methods to a point where reproducing the experiments are impossible. The number of cross validation folds is not specified, and libraries of the machine learning algorithms considered are not specified, nor definitions of their hyperparameter spaces." — Pipeline cannot be replayed because spec is incomplete. |
| 4 | `PR-EXP-0085-C05` | `publication_gate`, `seed_stability_gate`, `execution_attestation_gate` | + `prediction_replay_gate` | "Many of the tools do not have version numbers, which are necessary for reproducibility." — Pipeline-version drift; the *same* logical pipeline produces different results across tool versions. |
| 5 | `PR-052-C01` | `seed_stability_gate`, `execution_attestation_gate`, `model_selection_audit_gate`, `reporting_bias_gate` | + `prediction_replay_gate` | "Section on Model Development is unclear and poorly explained. Many details missing regarding architecture and optimization. No hyperparameter tuning described. … In current form, difficult to reproduce." — Architecture + tuning not specified → replay impossible. |
| 6 | `PR-102-C04` | `publication_gate`, `seed_stability_gate`, `execution_attestation_gate` | + `prediction_replay_gate` | "Code not available for review; preprocessing pipelines of proprietary MLCS framework not disclosed; … reproducibility concerns." — Closed/proprietary pipeline cannot be replayed by anyone outside the vendor. |
| 7 | `PR-005-C07` | `seed_stability_gate`, `execution_attestation_gate` | + `prediction_replay_gate` | "There is a general lack of details (data more than code) for the work to be reproduced." — Generic but classic replay-blocker. |
| 8 | `PR-EXP-0105-C02` | `publication_gate`, `seed_stability_gate`, `execution_attestation_gate`, `reporting_bias_gate` | + `prediction_replay_gate` | "Without data and source code, the value of this study is significantly diminished and evaluation of the methodology is impossible. … At the very least, a working source code and simulated data should be made available." — Reviewer explicitly asks for the artifacts needed to re-execute. |

**Secondary candidates** (not in the top 8 but worth considering if reviewer wants ≥10):
- `PR-007-C05` (training-set construction not reproducible)
- `PR-010-C05` (feature aggregation unclear → cannot reproduce)
- `PR-015-C02` (synthetic-data papers without code/data)
- `PR-034-C04` (model on "reasonable request only")
- `PR-107-C05` (hyperparameters not stated)
- `PR-113-C06` (only pseudocode provided)
- `PR-EXP-0084-C06` (no code availability)
- `PR-EXP-0147-C02` (preprocessing undocumented; reviewer asks "what was the reproducibility of the signals' measurement?" — explicit replay framing)
- `PR-EXP-0155-C06` (code not made public)
- `PR-EXP-0191-C04` (no code → no reproducibility)
- `PR-EXP-0194-C03` (partial data sharing)

### A.2 `robustness_gate` (target: +5–10; proposing **+10**)

The gate checks model behaviour under perturbation: subgroup performance disparities, temporal/concept drift, distribution shift between train and deploy, sensitivity analyses to preprocessing/hyperparameter choices, scanner / batch / annotator variability. The KB has 52 concerns with `subgroup_*` / `distribution_shift*` / `temporal_drift` / `scanner_*` / `batch_effect*` / `robustness*` tags that do NOT include `robustness_gate`. The 10 strongest are below.

| # | concern_id | current `mlgg_gates` | suggested addition | justification |
|---|---|---|---|---|
| 1 | `PR-010-C02` | `split_protocol_gate`, `covariate_shift_gate` | + `robustness_gate` | "The use of data from 20 past years is problematic — medicine has taken a great leap forward. … Instead of randomly splitting, temporal partitioning would more accurately estimate deployment performance." — Textbook **temporal drift / concept drift** robustness concern (severity CRITICAL). |
| 2 | `PR-EXP-0160-C02` | `distribution_generalization_gate`, `covariate_shift_gate`, `external_validation_gate` | + `robustness_gate` | "By far the most patients are included before treatment protocols were changed around the world to exclude antibiotics and include remdesivir, dexamethasone …" — Concrete **temporal drift** (treatment-era shift) within the training window. |
| 3 | `PR-EXP-0157-C06` | `cohort_definition_gate`, `distribution_generalization_gate`, `generalization_gap_gate`, `covariate_shift_gate` | + `robustness_gate` | Hamamatsu vs Aperio scanner: "it would be helpful to see a similar analysis for a model trained on a dataset with both scanners, and also the reverse." — Canonical **scanner-robustness** sensitivity request. |
| 4 | `PR-EXP-0150-C07` | `external_validation_gate`, `covariate_shift_gate` | + `robustness_gate` | "Can the authors devise a way to merge these datasets accounting for batch effects?" — **Batch-effect robustness** across studies. |
| 5 | `PR-EXP-0086-C10` | `fairness_equity_gate`, `shap_interpretability_gate` | + `robustness_gate` | "The discussion did not address subgroup performance disparities, particularly regarding ethnicity…" — **Subgroup performance stability** (also fairness, but the robustness framing is explicit). |
| 6 | `PR-EXP-0193-C02` | `feature_engineering_audit_gate`, `feature_lineage_gate`, `evaluation_quality_gate` | + `robustness_gate` | "Different operators can generate different ROI. … how will this inter-operator variance affect the results?" — Robustness to **annotator / input-perturbation** variance. |
| 7 | `PR-EXP-0153-C03` | `feature_engineering_audit_gate`, `clinical_metrics_gate`, `model_selection_audit_gate` | + `robustness_gate` | "Show the sensitivity of the UQ to the mild changes of tuning parameters in those procedures." — Explicit **sensitivity-analysis** request on preprocessing pipeline. Existing tag already includes `robustness`. |
| 8 | `PR-EXP-0086-C07` | `evaluation_quality_gate`, `clinical_metrics_gate` | + `robustness_gate` | "Including additional sensitivity analyses, such as precision-recall curves, ROC curves, or decision threshold analyses…" — Threshold-sensitivity / metric-stability analysis. |
| 9 | `PR-EXP-0097-C13` | `split_protocol_gate`, `clinical_metrics_gate` | + `robustness_gate` | "What happens if the splitting ratio is 70%/30% and 80%/20%?" — **Split-ratio robustness** sensitivity (existing tag already `train_test_split_robustness`). |
| 10 | `PR-EXP-0101-C02` | `cohort_definition_gate` | + `robustness_gate` | "To show robustness, maybe the authors could experiment on other diseases as well." — Reviewer explicitly invokes "robustness" via cross-outcome demonstration. Existing tag already `robustness_across_outcomes`. |

**Secondary candidates** (high-quality but slot-limited):
- `PR-002-C04` (CV more robust than single split)
- `PR-007-C04` (sensitivity dropped 96% → 86% across sites)
- `PR-101-C01` (small sample limits robustness of ML models)
- `PR-112-C01` (external AUC drop contradicting "robustness" claim) — strong candidate
- `PR-112-C05` (selective reporting of robustness)
- `PR-004-C04` (VA vs MIMIC distribution shift)
- `PR-025-C02` (no sensitivity analyses for missing-data handling)
- `PR-023-C01` (FDR threshold sensitivity analysis missing)
- `PR-EXP-0085-C06` (cross-species robustness benchmarking missing)
- `PR-EXP-0096-C02` (CV averaging not robust)
- `PR-EXP-0095-C02` (development vs validation clinical setting shift — CRITICAL)
- `PR-EXP-0212-C06` (adjMMD–AUC drop association = robustness metric validation)

---

## Proposal B — New synthetic concerns

**Not proposed.** Re-tagging alone supplies 8 concerns for `prediction_replay_gate` and 10 for `robustness_gate`, exceeding the ≥5 target for both. Per the project rule preferring real peer-review provenance over synthetic content, synthetic concerns should only be added if reviewer-tag inventory is exhausted. It is not.

If future eval still shows weak coverage after applying Proposal A, candidates for synthetic concerns include (NOT proposed now):
- Replay: a concern about pipeline-version drift between dev (Python 3.10 + sklearn 1.3) and prod (Python 3.11 + sklearn 1.5) producing different predictions on the same input.
- Robustness: a concern about adversarial / OOD prompt perturbation for LLM-based clinical decision support (very few KB entries cover LLM evaluation).

If added, each must carry `_synthetic: true` and `_synthesis_rationale` per the agent's brief.

---

## Application instructions for the user

### Option 1 — manual (recommended for KB-write rule)

Open `references/case-studies/peer-review-kb.json`, locate each concern_id listed above, and append the new gate string to its `mlgg_gates` list. Re-run the audit script (`references/case-studies/parse_peer_reviews.py` or whatever the standard tooling is) to refresh `peer-review-kb-stats.json`.

### Option 2 — scripted (DO NOT execute without explicit user approval)

A small `apply_F4_proposal.py` script (provided here as a *suggestion*, not executed) would look like:

```python
# scripts/curation/apply_F4_proposal.py — NOT RUN BY F4
import json, pathlib

KB = pathlib.Path("references/case-studies/peer-review-kb.json")
ADDITIONS = {
    # prediction_replay_gate
    "PR-EXP-0200-C04": "prediction_replay_gate",
    "PR-EXP-0119-C09": "prediction_replay_gate",
    "PR-EXP-0084-C04": "prediction_replay_gate",
    "PR-EXP-0085-C05": "prediction_replay_gate",
    "PR-052-C01":      "prediction_replay_gate",
    "PR-102-C04":      "prediction_replay_gate",
    "PR-005-C07":      "prediction_replay_gate",
    "PR-EXP-0105-C02": "prediction_replay_gate",
    # robustness_gate
    "PR-010-C02":      "robustness_gate",
    "PR-EXP-0160-C02": "robustness_gate",
    "PR-EXP-0157-C06": "robustness_gate",
    "PR-EXP-0150-C07": "robustness_gate",
    "PR-EXP-0086-C10": "robustness_gate",
    "PR-EXP-0193-C02": "robustness_gate",
    "PR-EXP-0153-C03": "robustness_gate",
    "PR-EXP-0086-C07": "robustness_gate",
    "PR-EXP-0097-C13": "robustness_gate",
    "PR-EXP-0101-C02": "robustness_gate",
}

data = json.loads(KB.read_text())
hits = 0
for entry in data["entries"]:
    for c in entry.get("reviewer_concerns", []):
        cid = c.get("concern_id")
        if cid in ADDITIONS:
            gates = c.setdefault("mlgg_gates", [])
            new_gate = ADDITIONS[cid]
            if new_gate not in gates:
                gates.append(new_gate)
                hits += 1

# Increment change_log
data.setdefault("change_log", []).append({
    "date": "2026-05-16",
    "author": "F4_kb_curation",
    "change": f"Added prediction_replay_gate / robustness_gate tags to {hits} existing concerns",
    "proposal": "F4_kb_curation_proposal.md",
})
KB.write_text(json.dumps(data, indent=2, ensure_ascii=False))
print(f"Updated {hits} concerns")
```

User should review, run with `--dry-run` first (add that flag), and commit the diff manually.

---

## Expected impact

If Proposal A is applied:

| Gate | Concerns before | Concerns after | Expected top-1 score | Expected P@5 |
|---|---|---|---|---|
| `prediction_replay_gate` | 1 | 9 | 0.033 → **>0.45** | ~0 → **≥0.6** |
| `robustness_gate` | 7 | 17 | 0.368 → **>0.55** | ~0.2 → **≥0.7** |

The score predictions assume the existing RAG embedding pipeline; if the gate query text is generic ("model robustness under distribution shift"), the new concerns about temporal drift / scanner shift / subgroup disparity should rank in the top-5.

---

## Constraints honored

- [x] No KB writes performed (CLAUDE.md §68 rule respected).
- [x] Re-tagging proposals strongly preferred over synthetic; synthetic concerns not added.
- [x] No fabricated citations — every proposed addition references an existing real concern with verifiable `concern_id`.
- [x] Proposal is a single markdown file at `/tmp/F4_kb_curation_proposal.md` outside the repo (no source files touched).
- [x] No git commit performed; F1/F2/F3/F5 commits are not interfered with.

---

## Audit data (for reviewer cross-check)

- Total KB entries: 335
- Total reviewer concerns: 817
- Re-tagging candidates surfaced (text-keyword search, word-boundary regex): 20 for `prediction_replay_gate`, 25 for `robustness_gate`
- Re-tagging candidates surfaced via tag-field search: additional 52 for `robustness_gate` (subgroup_*, distribution_shift, temporal_drift, scanner_*, batch_effects, robustness, …)
- Final selection: top 8 / top 10 by relevance and severity diversity (CRITICAL → HIGH → MEDIUM mix)
