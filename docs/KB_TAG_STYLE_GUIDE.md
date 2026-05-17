# KB Tag Style Guide

**Status**: living document — extend as KB grows.
**Authority**: Wave 8 W6 / W7-P6 followup (2026-05-17).
**Scope**: `references/case-studies/peer-review-kb.json` `reviewer_concerns[].tags`.

## Why this guide exists

The W7-P6 KB audit measured tag distribution across the current 335 entries
/ 817 reviewer concerns:

- 1977 unique tags
- 2419 total tag uses
- **1770 singletons (89.5% of unique tags used exactly once)**
- Only 32 tags meet the canonical threshold (>=5 uses)

This kills the `tag_overlap` corroboration signal: only ~2% of within-CP
concern pairs share even one tag. RAG retrieval then has to lean entirely
on text similarity, which is what tags were supposed to backstop.

Root cause: each reviewer extracts tags free-text, with no shared
vocabulary. Every paper-specific narrowing (`class_imbalance_across_centers`,
`no_external_validation_for_combined`) becomes its own singleton instead
of reinforcing the canonical base (`class_imbalance`, `no_external_validation`).

Going forward: **prefer the canonical tags below** unless your concern
genuinely needs a paper-specific narrowing. When in doubt, use the broader
canonical tag and put the paper-specific context in `concern_text`.

## Canonical tag vocabulary (>=5 uses in current KB)

Grouped by dominant MLGG gate. Use counts reflect the 2026-05-17 KB snapshot.

### Cohort definition (`cohort_definition_gate`)
- `outcome_definition` (10)
- `selection_bias` (10)
- `cohort_definition` (7)

### Sample size (`sample_size_gate`)
- `small_sample` (8)
- `underpowered` (8)

### Evaluation quality (`evaluation_quality_gate`)
- `class_imbalance` (14) — top canonical
- `missing_calibration` (8)
- `auprc_missing` (6)
- `incomplete_metrics` (6)
- `marginal_improvement` (6)
- `modest_performance` (6)
- `multiple_testing` (5)

### Discrimination & clinical utility (`clinical_metrics_gate`)
- `incremental_value` (7)
- `sensitivity_analysis` (7)

### Calibration & decision-curve (`calibration_dca_gate`)
- `calibration_plot_missing` (5)

### External validation & generalization (`external_validation_gate`)
- `no_external_validation` (9)
- `generalizability` (5)

### Model selection audit (`model_selection_audit_gate`)
- `model_justification` (11)
- `ablation_missing` (8)
- `missing_baseline_comparison` (6)
- `overfitting_risk` (5)
- `multiple_model_comparison` (5)

### Feature engineering (`feature_engineering_audit_gate`)
- `feature_selection_justification` (5)

### Missingness policy (`missingness_policy_gate`)
- `missing_data_unreported` (5)

### Fairness & equity (`fairness_equity_gate`)
- `confounding` (5)

### Reproducibility — seed & runtime (`seed_stability_gate`)
- `reproducibility` (13)

### Reproducibility — execution attestation (`execution_attestation_gate`)
- `irreproducible_methods` (8)
- `no_code_availability` (7)

### Reporting & TRIPOD (`reporting_bias_gate`)
- `overstatement` (8)
- `no_tripod` (6)
- `missing_demographics` (5)
- `tripod_compliance` (5)

**Total: 32 canonical tags spanning 13 MLGG dimensions.**

## When to add a NEW tag

1. **Check this list first.** Is there an existing canonical that fits, even
   imperfectly? If yes, use it and put the nuance in `concern_text`.
2. **If you genuinely need a new tag**, make it BROAD:
   - Single underscore-separated phrase.
   - No paper-specific suffixes (`_for_X`, `_in_Y`, `_across_Z`).
   - Should plausibly recur across many papers.
3. **Document growth.** If a new tag earns >=5 uses, this guide should be
   updated to promote it to canonical.

## Anti-patterns (from W7-P6 audit)

The audit found these recurring failure modes. All examples are real
singletons in the current KB:

### 1. Paper-specific narrowing with `_for_*`, `_in_*`, `_across_*`, `_with_*`

The paper-specific context belongs in `concern_text`, **not** in the tag.

| Singleton found | Should be |
|---|---|
| `no_external_validation_for_combined` | `no_external_validation` |
| `class_imbalance_across_centers` | `class_imbalance` |
| `generalizability_across_centers` | `generalizability` |
| `sensitivity_analysis_for_size` | `sensitivity_analysis` |
| `calibration_in_supplement_only` | `missing_calibration` |
| `temporal_validation_in_supplement` | `temporal_validation` |
| `external_validation_with_gold_standard` | `external_validation` |
| `comparison_with_prior_work` | `missing_baseline_comparison` |

Counts of suffix singletons in current KB: 26 `_in_*`, 7 `_for_*`,
5 `_with_*`, 4 `_across_*`.

### 2. Padding around an existing canonical

Re-stating a canonical concept with a synonym or modifier creates a
singleton instead of reinforcing the canonical:

| Singleton found | Use canonical |
|---|---|
| `reproducibility_methods_underspecified` | `reproducibility` |
| `partial_reproducibility` | `reproducibility` |
| `external_validation_incomplete` | `no_external_validation` |
| `external_validation_details` | `no_external_validation` |
| `external_validation_depth` | `no_external_validation` |
| `no_formal_calibration_test` | `missing_calibration` |
| `metrics_missing` | `incomplete_metrics` |
| `missing_demographics_table` | `missing_demographics` |

### 3. Overly specific compound concepts

If the concept is genuinely new and broad, add it as a base tag. If it is
a one-paper detail, drop it and put the detail in `concern_text`.

## Future enforcement

Wave 9 will add a `lint_kb_tags` diagnostic that warns on:

- New tags ending in `_for_*`, `_in_*`, `_when_*`, `_during_*`, `_across_*`, `_with_*`
- New tags not in this guide AND appearing in <2 concerns after their CP closes
- Tags that are obvious padding of a canonical (substring match heuristic)

Wave 9 will also include a one-shot canonicalization sweep over the existing
1770 singletons — that backlog is **out of scope** for this guide. This
doc's job is to stop the bleed on **new** entries.

For now: **manual review** by anyone editing
`references/case-studies/peer-review-kb.json`. When you add a concern,
look here first.

## Provenance

- Numbers in this doc reflect the KB as of 2026-05-17 (commit before W8-W6).
- Recompute via:
  ```python
  import json
  from collections import Counter
  data = json.load(open('references/case-studies/peer-review-kb.json'))
  tag_freq = Counter()
  for e in data['entries']:
      for c in e.get('reviewer_concerns', []):
          for t in c.get('tags', []):
              tag_freq[t] += 1
  canonical = sorted(
      [(t, n) for t, n in tag_freq.items() if n >= 5],
      key=lambda x: -x[1],
  )
  ```
- Source audit: W7-P6 (see commit `889b0ec` ancestors and
  `references/case-studies/peer-review-kb-audit-2026-04.md`).
