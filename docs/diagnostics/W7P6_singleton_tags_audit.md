# W7-P6: KB singleton-tag fragmentation audit

**Date**: 2026-05-17
**Agent**: Wave7-P6 (diagnostic-only, no KB writes, no commits)
**Source**: `references/case-studies/peer-review-kb.json`
**Triggered by**: W2 finding of `no_external_validation_for_combined` (PR-006-C04) — paper-specific narrow variant of canonical `no_external_validation`.

## Global stats

| Metric | Value |
|---|---|
| KB entries | 335 |
| Total concerns | 817 |
| Total tag uses | 2,419 |
| Unique tags | 1,977 |
| Singleton tags (1 use) | 1,770 (89.5%) |
| Concerns with >=1 singleton tag | 746 / 817 (91.3%) |

**Interpretation**: 89.5% of the tag vocabulary is one-shot. The
`tag_overlap` similarity signal can never fire on a singleton — every
singleton is a dead-end branch in the retrieval graph.

## Narrowing patterns detected

Two heuristics, both restricted to singletons whose stem is a
non-singleton canonical tag (>=2 uses):

| Pattern | Count |
|---|---|
| Structural suffix (`X_for_Y`, `X_in_Y`, `X_when_Y`, `X_during_Y`, `X_with_Y`, `X_across_Y`, `X_between_Y`) | 6 |
| **Prefix-of-canonical** (singleton starts with canonical base, e.g. `reproducibility_limited` -> `reproducibility`) | **64** |
| Suffix-of-canonical (singleton ends with canonical base) | 47 |
| **Total candidate canonicalizations** | **~111** (some overlap) |

The original W2 finding (`no_external_validation_for_combined`) is one
of 64 prefix-narrowing cases — confirming the pattern repeats across
the KB at scale.

## Top 20 prefix-narrowings (highest base frequency = highest ROI)

| Singleton tag | Canonical base | Base uses | Example concern |
|---|---|---|---|
| `class_imbalance_across_centers` | `class_imbalance` | 14 | PR-055-C02 |
| `reproducibility_limited` | `reproducibility` | 13 | PR-EXP-0187-C03 |
| `reproducibility_methods_underspecified` | `reproducibility` | 13 | PR-EXP-0084-C04 |
| `reproducibility_documentation` | `reproducibility` | 13 | PR-EXP-0085-C05 |
| `reproducibility_resolved` | `reproducibility` | 13 | PR-EXP-0191-C04 |
| `outcome_definition_unvalidated` | `outcome_definition` | 10 | PR-EXP-0160-C12 |
| `outcome_definition_inconsistent` | `outcome_definition` | 10 | PR-EXP-0150-C04 |
| `selection_bias_discussion` | `selection_bias` | 10 | PR-EXP-0197-C03 |
| `outcome_definition_ambiguous` | `outcome_definition` | 10 | PR-074-C02 |
| `no_external_validation_initially` | `no_external_validation` | 9 | PR-EXP-0097-C01 |
| `no_external_validation_for_combined` | `no_external_validation` | 9 | **PR-006-C04 (W2 finding)** |
| `small_sample_high_fold` | `small_sample` | 8 | PR-EXP-0103-C06 |
| `sensitivity_analysis_missing` | `sensitivity_analysis` | 7 | PR-EXP-0084-C03 |
| `sensitivity_analysis_for_size` | `sensitivity_analysis` | 7 | PR-012-C07 |
| `incremental_value_not_tested` | `incremental_value` | 7 | PR-019-C02 |
| `cohort_definition_ambiguous` | `cohort_definition` | 7 | PR-EXP-0084-C01 |
| `cohort_definition_inconsistency` | `cohort_definition` | 7 | PR-EXP-0086-C01 |
| `marginal_improvement_significance` | `marginal_improvement` | 6 | PR-EXP-0159-C02 |
| `confounding_by_stage` | `confounding` | 5 | PR-005-C02 |
| `generalizability_across_centers` | `generalizability` | 5 | PR-EXP-0124-C01 |

## Most-fragmented canonical bases (consolidation targets)

| Canonical base | Singleton variants found | Base uses |
|---|---|---|
| `clinical_utility` | 6 | 2 |
| `confounding` | 5 | 5 |
| `reproducibility` | 4 | 13 |
| `label_definition` | 4 | 2 |
| `confounders` (likely should merge with `confounding`) | 3 | 2 |
| `feature_importance` | 3 | 2 |
| `code_unavailable` | 3 | 2 |
| `outcome_definition` | 3 | 10 |
| `distribution_shift` | 3 | 4 |
| `no_external_validation` | 2 | 9 |
| `sensitivity_analysis` | 2 | 7 |
| `cohort_definition` | 2 | 7 |
| `generalizability` | 2 | 5 |

## Recommendation

**Narrowings = 64 (well over the 50 threshold) — warrants a Wave 8
canonicalization sweep.**

Proposed Wave 8 task:
1. Build canonicalization map (singleton `X_<modifier>` -> base `X`) for
   the 64 prefix cases. Manual gate: reviewer accepts/rejects each.
2. Apply rename in `peer-review-kb.json` (single edit pass, deterministic).
3. Side-effect cleanup: merge `confounders` (2 uses) into `confounding`
   (5 uses) — looks like a stem-variation split.
4. Expected gain: each accepted rename adds N-1 new edges the
   `tag_overlap` similarity signal can traverse. Conservative estimate:
   ~150–300 additional retrieval pairs across the KB (sum of base-uses
   for accepted bases).
5. Risk: lose paper-specific nuance. Mitigation: preserve narrow tag
   text in the concern's `description` or a new `qualifiers` field
   before renaming.

Bigger-picture finding worth flagging upstream: with 89.5% singleton
rate, the `tag_overlap` signal is operating on a near-disconnected graph.
Even after the 64 prefix renames, ~1,700 singletons remain. Long-term,
the KB likely needs a controlled vocabulary (a fixed tag taxonomy with
free-text `qualifiers`) rather than ad-hoc tagging per entry.

## Compliance

- No KB writes performed.
- No commits performed.
- Audit data only.
