# Peer-Review KB Audit — 2026-04

Scope: `references/case-studies/peer-review-kb.json` (375 reviewer concerns across 106 NC papers).
Trigger: P0-3 in `plans/list-eager-beacon.md` — verify whether low `data_leakage` category count (3/375 ≈ 0.8%) reflects (a) reviewer focus, (b) miscategorization, or (c) broken retrieval indexing.

## TL;DR

**The category field is roughly honest, but the `mlgg_gates` retrieval index is broken.**

- Only 3/375 concerns are labeled `category: data_leakage`. Sampling 30 non-leakage concerns, I found **0 clear miscategorizations** where `category` is obviously wrong. The low count is real — published-paper reviews are post-filtered for egregious leakage.
- But: **16 concerns have leakage-adjacent terms in their `tags` field** (`target_leakage`, `data_leakage_via_imputation`, `data_leakage_via_tuning`, `patient_overlap`, `future_information_leakage`, etc.), and only **3/16 (19%)** are mapped to `leakage_gate` in `mlgg_gates`.
- Worse, the retrieval index is systemically incomplete: **276/375 (73.6%) concerns have empty `mlgg_gates` arrays**. Any user query of the form `peer_review_lookup.py --gate <name>` silently misses the vast majority of relevant concerns.

This means the SKILL.md advertised workflow — "Gate failed → query peer-review KB for reviewer backing" — under-delivers by ~4×.

## Method

1. Enumerated all 375 concerns; computed per-category counts.
2. Random-sampled 30 non-leakage concerns, seeded toward plausible hideaway categories (`preprocessing`, `study_design`, `model_selection`, `feature_selection`, `split_protocol`, `reporting`), seed=20260417.
3. Manually classified each sample: {clearly leakage miscategorized | borderline | correctly non-leakage}.
4. Scanned all 375 concerns for leakage-adjacent tags (keywords: `leakage`, `leak`, `overlap`, `contamination`, `peek`, `temporal_split`, `cross_split`, `patient_overlap`, `test_peeking`, `data_leak`).
5. Counted empty `mlgg_gates` to measure retrieval-index health.

## Findings

### (A) Category field is acceptable

Of 30 sampled non-leakage concerns:

- **0** clear miscategorizations (concern is leakage but category says otherwise)
- **3 borderline** cases — all already tagged `split_protocol` or `preprocessing`, which is defensible:
  - PR-029-C03 "multiple admissions per patient" → `split_protocol` (patient-level splitting)
  - PR-010-C02 "temporal partitioning beats random split" → `split_protocol`
  - PR-003-C03 "imputation on validation cohort" → `preprocessing`
- **27** correctly non-leakage (evaluation gaps, cohort matching, reporting clarity, external validation, etc.)

**Interpretation**: The 3/375 leakage count is not an artifact of mislabeling. It reflects the selection bias of published NC papers — papers with obvious leakage do not survive pre-publication review, so reviewer concerns on them skew toward evaluation/reporting polish.

### (B) `mlgg_gates` retrieval index is broken

Distribution of concerns with leakage-adjacent tags (N=16) by their `mlgg_gates` mapping:

| Mapped to | Count |
|---|---|
| `split_protocol_gate` | 3 |
| `leakage_gate` | 3 |
| `cohort_definition_gate` | 2 |
| `clinical_metrics_gate` | 1 |
| `missingness_policy_gate` | 1 |
| `tuning_leakage_gate` | 1 |
| `external_validation_gate` | 1 |
| **(empty)** | **6** |

Concrete miscoverage examples — all have leakage tags but will **not** surface when user runs `peer_review_lookup.py --gate leakage_gate`:

| Concern | Category | `mlgg_gates` | Leakage tags |
|---|---|---|---|
| PR-001-C02 | study_design | `[clinical_metrics_gate]` | `target_leakage`, `definition_variable`, `feature_is_outcome_proxy` |
| PR-003-C03 | preprocessing | `[missingness_policy_gate]` | `data_leakage_via_imputation` |
| PR-029-C03 | split_protocol | `[split_protocol_gate]` | `patient_overlap`, `multiple_admissions_per_patient` |
| PR-032-C05 | evaluation_metrics | `[]` | `data_leakage_via_tuning` |
| PR-064-C01 | reporting | `[]` | `potential_data_leakage_in_cv` |
| PR-072-C01 | **data_leakage** | `[]` | `data_leakage_via_correlated_phenotypes`, `train_test_overlap` |

Even concerns explicitly in the `data_leakage` category have empty `mlgg_gates` arrays — PR-072-C01 is a labeled leakage concern that the retrieval tool cannot return via gate query.

### (C) Overall index-health metric

**73.6% of concerns (276/375) have an empty `mlgg_gates` array.** The `peer_review_lookup.py --gate` command is usable for at most 26% of the KB.

## Recommended actions

This audit converts the original P0-3 plan ("relabel category if >20% misclassified") into a different, larger task: **fix the retrieval index, not the category field.** Revised priorities:

### P0-3a — Backfill `mlgg_gates` for leakage-tagged concerns (S, half day)

Target the 13 concerns in Finding (B) whose tags contain leakage terms but whose `mlgg_gates` excludes `leakage_gate`. Add `leakage_gate` to their gate list (don't remove existing mappings — a concern can route to multiple gates). Net effect: `--gate leakage_gate` returns ~16 concerns instead of 3, ~5× lift.

### P0-3b — Backfill all empty `mlgg_gates` arrays (M, 2–3 days)

Write a migration script that maps each concern's `category` + `tags` → at least one `mlgg_gates` entry using a deterministic rule table. Concerns with 0 gates is the symptom of the KB being assembled as a research corpus first, a retrieval index second. Target: reduce empty-gate count from 276 to <20.

### P0-3c — Update SKILL.md to describe actual KB coverage (S, 1h)

SKILL.md §"Peer Review Evidence Protocol" currently says "审稿人的原话比规则更有说服力" — but for leakage specifically, the KB has thin coverage by design (publication filter). Rewrite that section to:

- Acknowledge KB strength: evaluation / reporting / external validation / clinical utility (90% of concerns)
- Acknowledge KB limitation: leakage is rare in NC post-publication reviews; for leakage evidence, users should lean on `leakage_gate` + `mlgg-lint` rules R001-R027 rather than KB
- Remove or rephrase the statistic "107 papers × 375 concerns" implying uniform coverage

### NOT recommended

- Recategorizing the `category` field. The sample shows it's ~acceptable; re-labeling based on subjective leakage-adjacency would make the KB less auditable, not more.
- Expanding KB with more papers. The coverage problem is index structure, not volume.

## Reproducibility

The audit scripts are inline in this document's originating conversation; the exact sampling was `random.seed(20260417)` over `non_leakage_pool`, skewed to hideaway categories. To re-run:

```python
import json, random
random.seed(20260417)
kb = json.load(open('references/case-studies/peer-review-kb.json'))
all_concerns = [(e['id'], c) for e in kb['entries'] for c in e.get('reviewer_concerns', [])]
```

See findings (A)/(B)/(C) above for expected counts.
