# Fig 4 confusion matrix data

Trustable subset: **31** papers (cohort-binary scope + reviewer_concerns + peer_review_pdf_path)
Audited so far: **8** papers (lint payload available); awaiting **23** from Agent 2
Confusion matrix is computed on the **5** papers that are both audited and have at least one reviewer concern with `mlgg_gates` populated.

Audited paper IDs: PR-004, PR-007, PR-015, PR-026, PR-029, PR-058, PR-070, PR-086
Audited-with-gates paper IDs: PR-004, PR-007, PR-015, PR-026, PR-029
KB-curation gap (concerns exist but `mlgg_gates` empty): PR-038, PR-044, PR-045, PR-050, PR-058, PR-070, PR-084, PR-086, PR-096

## (a) Per-category confusion matrix (paper-level)

| Category | TP | FN | FP | TN | Reviewer N | mlgg N | Sens | Spec | PPV |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| leakage | 0 | 0 | 1 | 4 | 0 | 1 | n/a | 0.80 | 0.00 |
| imbalance | 0 | 0 | 0 | 5 | 0 | 0 | n/a | 1.00 | n/a |
| threshold_calibration | 0 | 1 | 1 | 3 | 1 | 1 | 0.00 | 0.75 | 0.00 |
| split_protocol | 1 | 0 | 1 | 3 | 1 | 2 | 1.00 | 0.75 | 0.50 |
| evaluation | 3 | 1 | 1 | 0 | 4 | 4 | 0.75 | 0.00 | 0.75 |
| model_selection | 0 | 0 | 2 | 3 | 0 | 2 | n/a | 0.60 | 0.00 |
| feature_engineering | 0 | 0 | 0 | 5 | 0 | 0 | n/a | 1.00 | n/a |
| reporting | 1 | 0 | 3 | 1 | 1 | 4 | 1.00 | 0.25 | 0.25 |

Definitions: TP = mlgg fired AND reviewer flagged the same category on the same paper; FN = reviewer flagged but mlgg did not; FP = mlgg fired but reviewer did not; TN = neither. Sensitivity = TP/(TP+FN) (mlgg recall vs reviewer); PPV = TP/(TP+FP).

## (b) Per-rule alignment with reviewer categories

| Rule | Categories | Papers fired | Reviewer aligned | Not aligned |
|---|---|---:|---:|---:|
| R002 | leakage | 1 | 0 | 1 |
| R004 | split_protocol | 2 | 1 | 1 |
| R005 | threshold_calibration | 1 | 0 | 1 |
| R008 | split_protocol | 1 | 1 | 0 |
| R009 | evaluation, reporting | 4 | 4 | 0 |
| R010 | evaluation | 1 | 1 | 0 |
| R013 | reporting | 2 | 1 | 1 |
| R018 | — | 1 | 0 | 1 |
| R019 | — | 2 | 0 | 2 |
| R021 | model_selection | 2 | 0 | 2 |
| R022 | evaluation | 3 | 3 | 0 |

## Overall

- reviewer category-hits across audited papers: 7
- mlgg overlap (TP) hits: 5
- overall mlgg recall vs reviewer: 71.43%
- mlgg-flagged categories not in reviewer concerns (extra issues per paper): 1.80
- lowest-sensitivity category: threshold_calibration
