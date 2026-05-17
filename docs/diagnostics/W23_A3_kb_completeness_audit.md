# W23-A3: NCPR v2 KB Completeness Audit

Per-paper quality scoring of `references/case-studies/peer-review-kb.json` (335 curated entries) for NCPR v2 holdout candidate selection. Read-only audit, no KB mutation.

## Scoring rubric (max 13)

| Signal | Points | Rationale |
|---|---:|---|
| `reviewer_concerns` >= 5 | +2 | deeper review = stronger ground truth |
| has CRITICAL or HIGH severity concern | +2 | tests system on hard cases |
| >= 3 distinct concern `category` values | +1 | cross-cutting paper |
| `paper_doi` AND `paper_title` populated | +1 | citable |
| `key_methodology_issues` populated | +2 | extractable query material |
| NOT in labeled_precision_at_5 / rag-eval-set | +3 | unseen by current eval |
| any concern has `author_response` text | +1 | rich dialogue |
| year <= 2025 | +1 | KB had time to extract |

Eval-used set (PR-ids appearing in `references/retrieval_eval/labeled_precision_at_5.json` or `references/case-studies/rag-eval-set.yaml`): **51 papers**. `references/retrieval_eval/scenarios.json` was scanned but references papers via tags only, no PR-ids, so it does not contribute exclusions.

## Score distribution

```
  13:    9  #########
  12:    1  #
  11:   56  ########################################################
  10:   56  ########################################################
   9:    6  ######
   8:   14  ##############
   7:    6  ######
   6:    5  #####
   5:  163  ################################################################################
   4:   18  ##################
   3:    1  #
```

- Total entries scored: **335**
- Score >= 7 (high-quality eligible): **148**
- Score >= 10: **122**
- Score == 13 (max): **9**

Bimodal: a large cluster at 5 (n=163) are mostly minimally-curated entries lacking `key_methodology_issues` and severity tagging; high-quality cluster at 10-11 (n=112) is the working pool.

## Top 50 candidates (NCPR v2 holdout priority pool)

| paper_id | journal | year | n_concerns | score | notes |
|---|---|---:|---:|---:|---|
| PR-013 | Nature Communications | 2023 | 6 | 13 | CRIT/HIGH |
| PR-106 | Nature Communications | 2025 | 6 | 13 | CRIT/HIGH, 5cats |
| PR-017 | Nature Communications | 2024 | 5 | 13 | CRIT/HIGH, 5cats |
| PR-018 | Nature Communications | 2023 | 5 | 13 | CRIT/HIGH |
| PR-019 | Nature Communications | 2024 | 5 | 13 | CRIT/HIGH |
| PR-020 | Nature Communications | 2025 | 5 | 13 | CRIT/HIGH |
| PR-034 | Nature Communications | 2024 | 5 | 13 | CRIT/HIGH |
| PR-055 | Nature Communications | 2024 | 5 | 13 | CRIT/HIGH |
| PR-066 | Nature Communications | 2025 | 5 | 13 | CRIT/HIGH |
| PR-043 | Nature Communications | 2025 | 5 | 12 | CRIT/HIGH |
| PR-EXP-0160 | Nature Communications | 2021 | 15 | 11 | CRIT/HIGH, 8cats, no-kmi |
| PR-EXP-0097 | Nature Communications | 2025 | 14 | 11 | CRIT/HIGH, 7cats, no-kmi |
| PR-EXP-0109 | Nature Communications | 2024 | 14 | 11 | CRIT/HIGH, 8cats, no-kmi |
| PR-EXP-0095 | Nature Communications | 2025 | 12 | 11 | CRIT/HIGH, 7cats, no-kmi |
| PR-EXP-0110 | Nature Communications | 2024 | 11 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0212 | Nature Communications | 2020 | 11 | 11 | CRIT/HIGH, 8cats, no-kmi |
| PR-EXP-0106 | Nature Communications | 2025 | 10 | 11 | CRIT/HIGH, no-kmi |
| PR-RO-07 | Nature Communications | 2025 | 10 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0098 | Nature Communications | 2025 | 9 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0101 | Nature Communications | 2025 | 9 | 11 | CRIT/HIGH, 5cats, no-kmi |
| PR-EXP-0112 | Nature Communications | 2024 | 9 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0119 | Nature Communications | 2024 | 9 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0096 | Nature Communications | 2025 | 8 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0105 | Nature Communications | 2025 | 8 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0170 | Nature Communications | 2021 | 8 | 11 | CRIT/HIGH, 5cats, no-kmi |
| PR-EXP-0197 | Nature Communications | 2020 | 8 | 11 | CRIT/HIGH, 5cats, no-kmi |
| PR-EXP-0209 | Nature Communications | 2020 | 8 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0103 | Nature Communications | 2025 | 7 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0126 | Nature Communications | 2024 | 7 | 11 | CRIT/HIGH, no-kmi |
| PR-EXP-0150 | Nature Communications | 2022 | 7 | 11 | CRIT/HIGH, no-kmi |
| PR-EXP-0200 | Nature Communications | 2020 | 7 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0203 | Nature Communications | 2020 | 7 | 11 | CRIT/HIGH, 5cats, no-kmi |
| PR-042 | Nature Communications | 2026 | 6 | 11 | CRIT/HIGH |
| PR-EXP-0092 | Nature Communications | 2025 | 6 | 11 | CRIT/HIGH, no-kmi |
| PR-EXP-0099 | Nature Communications | 2025 | 6 | 11 | CRIT/HIGH, no-kmi |
| PR-EXP-0124 | Nature Communications | 2024 | 6 | 11 | CRIT/HIGH, 5cats, no-kmi |
| PR-EXP-0127 | Nature Communications | 2024 | 6 | 11 | CRIT/HIGH, no-kmi |
| PR-EXP-0155 | Nature Communications | 2022 | 6 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0157 | Nature Communications | 2022 | 6 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0159 | Nature Communications | 2021 | 6 | 11 | CRIT/HIGH, no-kmi |
| PR-EXP-0185 | Nature Communications | 2021 | 6 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0191 | Nature Communications | 2021 | 6 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0194 | Nature Communications | 2021 | 6 | 11 | CRIT/HIGH, 6cats, no-kmi |
| PR-EXP-0198 | Nature Communications | 2020 | 6 | 11 | CRIT/HIGH, 5cats, no-kmi |
| PR-EXP-0205 | Nature Communications | 2020 | 6 | 11 | CRIT/HIGH, 5cats, no-kmi |
| PR-EXP-0147 | Nature Communications | 2022 | 5 | 11 | CRIT/HIGH, 5cats, no-kmi |
| PR-EXP-0148 | Nature Communications | 2022 | 5 | 11 | CRIT/HIGH, no-kmi |
| PR-EXP-0149 | Nature Communications | 2022 | 5 | 11 | CRIT/HIGH, no-kmi |
| PR-EXP-0179 | Nature Communications | 2021 | 5 | 11 | CRIT/HIGH, 5cats, no-kmi |
| PR-EXP-0192 | Nature Communications | 2021 | 5 | 11 | CRIT/HIGH, 5cats, no-kmi |

## Worst 10 (likely stubs - exclude from holdout)

| paper_id | journal | year | n_concerns | score | reason |
|---|---|---:|---:|---:|---|
| PR-EXP-0010 | Communications Medicine | 2026 | 0 | 4 | no concerns, no kmi, no CRIT/HIGH |
| PR-EXP-0011 | Communications Medicine | 2026 | 0 | 4 | no concerns, no kmi, no CRIT/HIGH |
| PR-EXP-0012 | Communications Medicine | 2026 | 0 | 4 | no concerns, no kmi, no CRIT/HIGH |
| PR-EXP-0013 | Communications Medicine | 2026 | 0 | 4 | no concerns, no kmi, no CRIT/HIGH |
| PR-EXP-0014 | Communications Medicine | 2026 | 0 | 4 | no concerns, no kmi, no CRIT/HIGH |
| PR-EXP-0015 | Communications Medicine | 2026 | 0 | 4 | no concerns, no kmi, no CRIT/HIGH |
| PR-EXP-0016 | Communications Medicine | 2026 | 0 | 4 | no concerns, no kmi, no CRIT/HIGH |
| PR-EXP-0087 | Nature Communications | 2026 | 0 | 4 | no concerns, no kmi, no CRIT/HIGH |
| PR-RO-02 | Nature Communications | 2026 | 0 | 4 | no concerns, no kmi, no CRIT/HIGH |
| PR-085 | Nature Communications | 2023 | 1 | 3 | no kmi, in eval, no CRIT/HIGH |

## Handoff to W23-B3 (holdout v2 criteria)

**Top 30 priority pool** (score >= 11, sorted by score desc then n_concerns desc):

```
  PR-013  PR-106  PR-017  PR-018  PR-019  PR-020
  PR-034  PR-055  PR-066  PR-043  PR-EXP-0160  PR-EXP-0097
  PR-EXP-0109  PR-EXP-0095  PR-EXP-0110  PR-EXP-0212  PR-EXP-0106  PR-RO-07
  PR-EXP-0098  PR-EXP-0101  PR-EXP-0112  PR-EXP-0119  PR-EXP-0096  PR-EXP-0105
  PR-EXP-0170  PR-EXP-0197  PR-EXP-0209  PR-EXP-0103  PR-EXP-0126  PR-EXP-0150
```

- All 30 are score 11+ (above the score-10 elbow of the distribution).
- All 30 are outside the current eval sets (labeled_precision_at_5 + rag-eval-set).
- 30/30 carry at least one CRITICAL/HIGH severity concern.
- Journal mix in top 30: Nature Communications=30
- Year mix in top 30: 2020=3, 2021=2, 2022=1, 2023=2, 2024=9, 2025=13

Pool is journal-concentrated in Nature Communications, reflecting which papers carry deep curated reviewer_concerns in the KB. W23-B3 may want to apply a per-journal cap and reach into the score-10 band (n=56) to diversify if a multi-journal holdout is required.

## Caveats

- "In eval" exclusion is based on literal PR-id matching; if NCPR v2 uses paraphrased queries, eval-set papers could still leak via tag/category overlap.
- Score 5 is the median because 163 entries lack `key_methodology_issues` AND have 0 reviewer_concerns scored above the threshold; they are likely auto-imported stubs awaiting curation, not buggy curations.
- All numbers reproducible from `/tmp/W23_A3_scored.json` (full sorted scoring artifact).
