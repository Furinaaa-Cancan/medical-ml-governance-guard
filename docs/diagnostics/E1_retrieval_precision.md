# E1: Retrieval Precision Audit

## Summary
- Queries tested: 12 / 12 (no crashes)
- **Mean P@5: 0.80**
- Strongest dimensions: Leakage, Calibration, Class imbalance, External validation, Reproducibility — all **P@5 = 1.0**
- Weakest dimensions: **Missing data (0.2)**, **AUROC-CI (0.2)**, **Temporal validation (0.3)**, **Tuning-on-test (0.4)**
- Defect categories found: 4 distinct (topical drift, severity-driven displacement, lexical-anchor failure, near-duplicates)
- Verdict: **Conditional** — strong on majority of MLGG dimensions but exhibits systematic drift on the four dimensions above

## Per-query results

Score key: **1** = clearly relevant, **0.5** = loosely related, **0** = irrelevant.

### Q1 — Leakage: "patient identifier leaked across train test split" — **P@5 = 1.0**
| Rank | ID | Sev | final | Concern (snippet) | Rel |
|---|---|---|---|---|---|
| 1 | PR-EXP-0109-C12 | CRITICAL | 0.412 | Verify external-val patients not in training set | 1 |
| 2 | PR-113-C01 | CRITICAL | 0.408 | SMOTE applied before split → synthetic leakage | 1 |
| 3 | PR-EXP-0185-C02 | HIGH | 0.405 | Patient imaged before+after 2018 — discarded from test? | 1 |
| 4 | PR-EXP-0110-C07 | CRITICAL | 0.401 | Same patients in cohort and original training | 1 |
| 5 | PR-072-C01 | CRITICAL | 0.396 | Train/test overlap on UK Biobank phenotypes | 1 |

### Q2 — Calibration: "no calibration plot or Brier score reported" — **P@5 = 1.0**
All 5 hits on missing calibration / Brier / Hosmer-Lemeshow (PR-EXP-0092-C03, PR-102-C01, PR-EXP-0109-C03, PR-025-C03, PR-110-C03). Textbook recall.

### Q3 — Subgroup fairness: "no subgroup analysis by race or sex" — **P@5 = 0.8**
| Rank | ID | Sev | final | Snippet | Rel |
|---|---|---|---|---|---|
| 1 | PR-EXP-0086-C10 | MEDIUM | 0.389 | Subgroup disparities by ethnicity | 1 |
| 2 | PR-078-C03 | HIGH | 0.385 | Stratified by sex × age × family history | 1 |
| 3 | PR-EXP-0105-C08 | MEDIUM | 0.384 | Under-representation of Black individuals | 0.5 |
| 4 | PR-EXP-0119-C01 | HIGH | 0.380 | Fitzpatrick V-VI underrepresented | 0.5 |
| 5 | PR-109-C02 | HIGH | 0.379 | Non-European ancestry too small to evaluate | 1 |

R3/R4 are about *demographic coverage* of the validation set, not subgroup performance analysis — partial credit.

### Q4 — Discrimination CI: "AUROC reported without confidence interval" — **P@5 = 0.2** (FAILURE)
| Rank | ID | Sev | final | Snippet | Rel |
|---|---|---|---|---|---|
| 1 | PR-011-C01 | HIGH | 0.414 | AUROC 0.71 modest — clinical impact discussion | 0.5 |
| 2 | PR-004-C01 | HIGH | 0.411 | AUROC vs Jaccard primary metric | 0.5 |
| 3 | PR-114-C02 | HIGH | 0.408 | AUROC 0.69 negative-result framing | 0 |
| 4 | PR-010-C03 | HIGH | 0.408 | AUROC on derivation set inappropriate | 0 |
| 5 | PR-EXP-0170-C06 | HIGH | 0.408 | AUROC vs AUPRC argument | 0 |

The query intent (missing 95% CI) is never matched. Embedding has anchored on the surface token "AUROC" and ignored "without confidence interval". The KB does contain CI-related concerns (PR-102-C01 mentions "95% CIs and paired DeLong") but they are buried below the AUROC-token cluster.

### Q5 — Tuning on test set: "model selection used the held-out test set" — **P@5 = 0.4**
| Rank | ID | Sev | final | Snippet | Rel |
|---|---|---|---|---|---|
| 1 | PR-111-C01 | CRITICAL | 0.431 | All-combinations search evaluated on test set | 1 |
| 2 | PR-EXP-0085-C02 | HIGH | 0.405 | External-val selection rationale | 0.5 |
| 3 | PR-EXP-0155-C03 | HIGH | 0.397 | Calibration leakage from test data | 0.5 |
| 4 | PR-027-C01 | MEDIUM | 0.394 | Why XGBoost vs others (canonical CP-005 boost) | 0 |
| 5 | PR-107-C03 | MEDIUM | 0.388 | DL benchmarking justification (canonical CP-005 boost) | 0 |

R4/R5 are pulled in by `canonical_pattern_id=CP-005` matching even though dense (0.65-0.66) is well below R1's 0.76. CP-005 ("model choice justification") is a different topic from "tuning on test" — the canonical-pattern channel is over-weighted here.

### Q6 — Class imbalance: "extreme class imbalance not addressed in evaluation" — **P@5 = 1.0**
PR-027-C02, PR-EXP-0085-C03, PR-EXP-0105-C03, PR-010-C04, PR-110-C04 — every hit explicitly about class imbalance / AUPRC / SMOTE. Excellent.

### Q7 — Missing data: "complete-case analysis dropped 40% of patients" — **P@5 = 0.2** (FAILURE)
| Rank | ID | Sev | final | Snippet | Rel |
|---|---|---|---|---|---|
| 1 | PR-007-C02 | CRITICAL | 0.372 | Malignancy class balance vs community | 0 |
| 2 | PR-EXP-0170-C05 | CRITICAL | 0.364 | Case/control ascertainment | 0 |
| 3 | PR-029-C03 | CRITICAL | 0.364 | Multiple admissions per patient | 0 |
| 4 | PR-035-C01 | HIGH | 0.362 | Complete-case vs imputed; missing-data threshold | 1 |
| 5 | PR-013-C03 | HIGH | 0.360 | Rate-of-decline per-patient regression | 0 |

The only on-topic hit (PR-035-C01, tagged `missingness_policy_gate`) ranks 4th. Three CRITICAL but topically-irrelevant concerns outrank it because the **+0.050 CRITICAL boost** flips them above the genuine HIGH match (dense gap is only ~0.02). The severity prior is too aggressive when dense scores are tight and uniformly low (all ≈0.62-0.66) — a signal that the KB simply lacks dense matches for "complete-case" and the system should have lowered confidence rather than substituted CRITICAL-severity neighbours.

### Q8 — Temporal validation: "no temporal hold-out for time-series prediction" — **P@5 = 0.3**
| Rank | ID | Sev | final | Snippet | Rel |
|---|---|---|---|---|---|
| 1 | PR-110-C02 | HIGH | 0.420 | Sample size for deterioration events | 0 |
| 2 | PR-010-C01 | CRITICAL | 0.413 | Bidirectional RNN uses future data | 1 |
| 3 | PR-009-C02 | MEDIUM | 0.409 | Bootstrap CIs vs model uncertainty | 0 |
| 4 | PR-024-C01 | CRITICAL | 0.408 | Prediction time horizon unspecified | 0.5 |
| 5 | PR-108-C02 | HIGH | 0.406 | Case-count power for predictors | 0 |

Drift to "sample size" via `canonical_pattern_id=CP-024`. Pattern matching is overpowering dense relevance on a known-thin topic.

### Q9 — External validation: "single-center development without external test" — **P@5 = 1.0**
PR-EXP-0086-C06, PR-EXP-0095-C03, PR-006-C04, PR-028-C01, PR-084-C01 — all on the nose.

### Q10 — Model spec: "deep neural network without architecture justification" — **P@5 = 0.8**
PR-107-C03, PR-EXP-0191-C06, PR-052-C01 directly on architecture/HP justification; PR-010-C01 (bidirectional RNN critique) and PR-EXP-0112-C02 (algorithm motivation) are loose.

### Q11 — Reproducibility: "code and data not available for replication" — **P@5 = 1.0**
PR-003-C09/C10, PR-015-C02, PR-EXP-0103-C07, PR-EXP-0092-C06 — all code/data availability.

### Q12 — TRIPOD compliance: "missing reporting items per TRIPOD AI checklist" — **P@5 = 0.9**
| Rank | ID | Sev | final | Note | Rel |
|---|---|---|---|---|---|
| 1 | PR-EXP-0157-C03 | MEDIUM | 0.427 | Add TRIPOD/STARD | 1 |
| 2 | PR-026-C04 | LOW | 0.415 | "follows TRIPOD+AI" (positive case) | 0.5 |
| 3 | PR-EXP-0148-C03 | MEDIUM | 0.410 | Add MI-CLAIM / TRIPOD-ML | 1 |
| 4 | PR-EXP-0092-C03 | CRITICAL | 0.407 | TRIPOD-cited calibration concern | 1 |
| 5 | PR-110-C06 | MEDIUM | 0.399 | No TRIPOD / MI-CLAIM compliance | 1 |

## Defect catalog

1. **Topical drift via canonical-pattern boost (Q5, Q8)** — CP-005 ("model choice justification") and CP-024 ("sample size") inject loosely-related concerns into top-5 with the +0.30 pattern bonus. Dense scores of pulled-in concerns are 0.65-0.69 versus 0.74-0.76 for genuine matches — the bonus is large enough to invert the order. Recommend gating the pattern bonus on a minimum dense floor (e.g. ≥0.70) or normalising relative to top-1 dense.

2. **Severity-boost displacement on thin topics (Q7)** — When the KB is lexically thin on a query ("complete-case", "missingness"), all dense scores cluster around 0.63 and the +0.050 CRITICAL boost is enough to push three off-topic CRITICALs above the only on-topic HIGH (PR-035-C01, the sole `missingness_policy_gate`-tagged match). Either cap the severity bonus relative to score spread or expose a "low confidence" flag when top-5 dense < 0.70.

3. **Lexical-anchor failure on negation/absence phrasing (Q4)** — "AUROC reported *without* confidence interval" matches purely on "AUROC", returning AUROC-discussion concerns instead of CI-missingness concerns. Bi-encoder cannot model absence; a re-ranker or BM25 weight bump on rare-token "confidence interval" would help. Note: bm25 score is 0.0 across all 5 hits, suggesting BM25 isn't firing meaningfully for this query — verify BM25 corpus indexing.

4. **Near-duplicate clustering acceptable (Q11)** — PR-003-C09 and PR-003-C10 are the same paper saying nearly the same thing ("I did not find the file with code" / "I didn't see a link to the code"). Two of five from the same paper. Not strictly wrong (both relevant) but reduces effective diversity; consider an MMR pass.

5. **No author-response leakage observed** — Across all 60 inspected hits, every concern_text was on-topic with the matching part of the embedding signal; no case where the rebuttal carried the relevance and the original concern did not. The A7 risk flagged in scope is **not visible** at top-5 on these 12 queries.

## Verdict

**Conditional pass.**

- The system is production-ready for 8/12 MLGG dimensions (leakage, calibration, fairness, imbalance, external validation, reproducibility, TRIPOD, model-spec).
- It is **not** production-ready as-is for missing-data, temporal-validation, tuning-on-test, and CI-reporting queries — three are KB-thin topics where the score-fusion priors (canonical_pattern bonus, severity bonus) drown out the dense signal.

**Most important fix:** make the canonical-pattern and severity bonuses **relative**, not additive. Either gate them on the top-1 dense floor (skip the bonus if dense < 0.70) or scale them by the dense-score spread within the candidate pool. This single change should recover Q5, Q7, Q8 without harming the already-perfect queries (where top-5 dense ≥ 0.72 and the bonuses are appropriate).

**Secondary fix:** the Q4 result strongly suggests BM25 isn't contributing on negation/absence queries — investigate why bm25_score=0.0 even when the query contains the high-IDF phrase "confidence interval".
