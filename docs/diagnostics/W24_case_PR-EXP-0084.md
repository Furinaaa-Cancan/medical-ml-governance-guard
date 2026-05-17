# W24-06 Case Study: PR-EXP-0084 — Real-paper MLGG run

> Stress test for recall: this paper carries **15 reviewer concerns**, roughly **2× the corpus average** for the PR-EXP batch. The W24-06 protocol runs the full retrieval-only pipeline (RAG → matcher → severity score → paper card) end-to-end on one paper and inspects the failure modes.

## Paper meta

- **Paper ID**: `PR-EXP-0084`
- **Title**: Precision phenotyping of type 2 diabetes in chinese populations using a variational autoencoder-informed tree model
- **DOI**: `10.1038/s41467-025-68211-4`
- **Journal / year**: Nature Communications (2026)
- **Prediction task**: Type-2 diabetes precision phenotyping in Chinese populations via VAE-informed tree model
- **Data type**: `ehr_tabular_clinical`
- **Sample size**: 56,000
- **Review rounds**: 3
- **Reviewer concerns**: 15 (Reviewer #1 contributed the bulk — KB extraction note flags this reviewer as unusually thorough, with 15 initial comments expanded to 45 in Round 2)

## Run config

- Pipeline: `synthesize_flags_from_rag` (post-67f7492 — emits `mlgg_gates[0]` as flag code instead of `concern_id`)
- `rag_query` `top_k=20` → returned **20** MLGG flags
- Matcher: `ncpr_matcher.match_all` (offline; `embed_fn=None` → semantic tier skipped, only `exact_code` / `code_prefix` / `category` fire)
- Severity scorer: `ncpr_severity_score.per_paper_score`
- Paper card: `ncpr_paper_card.make_paper_card`
- Query basis: `key_methodology_issues` is null on this entry → query synthesized from `paper_title` + `prediction_task` + `data_type` + concern-text excerpts (total 3 150 chars)

## Match summary

| Metric | Value |
|---|---|
| MLGG flags | 20 |
| Reviewer concerns | 15 |
| Matched concerns | 7 / 15 (47%) |
| Missed concerns (FN) | 8 |
| Over-flags (FP) | 13 |
| Weighted TP / FN / FP | 11.0 / 9.0 / 14.5 |
| Weighted precision | 0.431 |
| Weighted recall | 0.550 |
| **Weighted F1** | **0.484** |

### Per-severity breakdown

| Severity | Matched | Missed | Extra flags |
|---|---:|---:|---:|
| CRITICAL | 0 | 0 | 2 |
| HIGH | 4 | 1 | 10 |
| MEDIUM | 3 | 7 | 1 |
| LOW | 0 | 0 | 0 |

All matches resolved as `exact_code` at score 1.00 — no `code_prefix` or `category` fallback was needed (semantic tier is dark by design here).

## Matched (7 / 15)

- **[HIGH] PR-EXP-0084-C01** — gates pre-tagged: `cohort_definition_gate`
  - Concern: The description of the study population is not sufficient. It is described that included individuals are those with T2D within 12 months prior to baseline, where baseline is the first recorded instance of T2D in the database. This makes no sense, as that woul...
  - MLGG flag: `cohort_definition_gate` (type=`exact_code`, score=1.00)
- **[MEDIUM] PR-EXP-0084-C02** — gates pre-tagged: `cohort_definition_gate, clinical_metrics_gate, calibration_dca_gate`
  - Concern: There is a lack of justification as to why individuals with major medical conditions were excluded (exclusion criteria (d)).
  - MLGG flag: `clinical_metrics_gate` (type=`exact_code`, score=1.00)
- **[MEDIUM] PR-EXP-0084-C03** — gates pre-tagged: `feature_engineering_audit_gate, missingness_policy_gate, clinical_metrics_gate`
  - Concern: Outlier removal and rank normalization is performed without an explicit why (important!) and how (i.e. how was rank normalization in practice performed) and most importantly how many records it affects, and how it e.g. affects the results if it is not conside...
  - MLGG flag: `feature_engineering_audit_gate` (type=`exact_code`, score=1.00)
- **[HIGH] PR-EXP-0084-C04** — gates pre-tagged: `model_selection_audit_gate, tuning_leakage_gate, seed_stability_gate, execution_attestation_gate, prediction_replay_gate`
  - Concern: There is a lack of detail in the description of the methods to a point where reproducing the experiments are impossible. The number of cross validation folds is not specified, and libraries of the machine learning algorithms considered are not specified, nor...
  - MLGG flag: `model_selection_audit_gate` (type=`exact_code`, score=1.00)
- **[HIGH] PR-EXP-0084-C05** — gates pre-tagged: `evaluation_quality_gate, imbalance_policy_gate, clinical_metrics_gate`
  - Concern: It is claimed that the GBC method achieves 'highest accuracy' and therefore is chosen as a 'final model'. However, the authors are considering a multitude of outcomes so is that really the case for ALL of these? In addition, is accuracy really the best measur...
  - MLGG flag: `evaluation_quality_gate` (type=`exact_code`, score=1.00)
- **[HIGH] PR-EXP-0084-C08** — gates pre-tagged: `split_protocol_gate, tuning_leakage_gate, model_selection_audit_gate`
  - Concern: The manuscript lacks essential details on hyperparameter search spaces, selection criteria, and safeguards against data leakage. Model performance is reported without clear nested CV, fold definitions. It is also unclear when models use the full feature set v...
  - MLGG flag: `split_protocol_gate` (type=`exact_code`, score=1.00)
- **[MEDIUM] PR-EXP-0084-C13** — gates pre-tagged: `distribution_generalization_gate, external_validation_gate, fairness_equity_gate, covariate_shift_gate, shap_interpretability_gate`
  - Concern: BMI differences between ethnicities could introduce specific errors, especially in cases like this, where there is evidence of interplay of BMI with other risk factors. Does this also imply that the effect of BMI on diabetes phenotypes may have been masked du...
  - MLGG flag: `external_validation_gate` (type=`exact_code`, score=1.00)

## Missed (8 / 15)

- **[MEDIUM] PR-EXP-0084-C06** — category=`reproducibility`, gates pre-tagged: `publication_gate, seed_stability_gate, execution_attestation_gate, reporting_bias_gate`
  - Concern: Code availability: Given the lack of detail in the description of the methods and no code availability it is impossible to reproduce the presented results of the manuscript, even if one would have access to the data.
- **[HIGH] PR-EXP-0084-C07** — category=`feature_selection`, gates pre-tagged: `feature_engineering_audit_gate, feature_lineage_gate`
  - Concern: It remains unclear whether the VAE is used for representation learning, feature selection, denoising, or all three, and why this choice is preferable to simpler alternatives (e.g. a vanilla autoencoder, PCA, or purely supervised selection). Assertions about '...
- **[MEDIUM] PR-EXP-0084-C09** — category=`evaluation_metrics`, gates pre-tagged: `calibration_dca_gate, model_selection_audit_gate, evaluation_quality_gate`
  - Concern: The proposed 'stability' metric based on cosine similarity across independently trained VAEs is not valid given rotational/permutation of latent spaces.
- **[MEDIUM] PR-EXP-0084-C10** — category=`study_design`, gates pre-tagged: `cohort_definition_gate`
  - Concern: The inclusion of non-diabetic controls in representation learning is not sufficiently justified if the stated goal is to extract diabetes-specific patterns. The chosen case:control ratio is also not motivated. On the other hand, exclusion of multimorbid indiv...
- **[MEDIUM] PR-EXP-0084-C11** — category=`reporting`, gates pre-tagged: `execution_attestation_gate, clinical_metrics_gate, reporting_bias_gate, model_selection_audit_gate`
  - Concern: Statements about longitudinal 'phenotypic shift,' superiority of DDRTree over traditional clustering, mitigation of confounding via VAE-based selection, clinical relevance of the continuous model, and 'early interventions' are insufficiently supported by stat...
- **[MEDIUM] PR-EXP-0084-C12** — category=`reporting`, gates pre-tagged: `reporting_bias_gate, shap_interpretability_gate, fairness_equity_gate, cohort_definition_gate`
  - Concern: The observation was that HbA1c had modest effect, while lipids had the most substantial effect. This is surprising, as one would expect HbA1c to be the strongest driver when studying diabetes outcomes. Also, liver disease exerts an undue influence on specific...
- **[MEDIUM] PR-EXP-0084-C14** — category=`study_design`, gates pre-tagged: `cohort_definition_gate, reporting_bias_gate, external_validation_gate`
  - Concern: 'The data included all the patients whose data is accessible from the participating centers' medical record systems.' Were all the data during the period accessible in those centers? If not, what are the percentages of accessible data, and what determined the...
- **[MEDIUM] PR-EXP-0084-C15** — category=`feature_selection`, gates pre-tagged: `feature_engineering_audit_gate, feature_lineage_gate, clinical_metrics_gate`
  - Concern: The rationale for selecting exactly ten features in the final model is not clearly explained. Why was this number chosen? It would be helpful if the authors could clarify whether they tested different numbers of input features and how this affected the tree s...

## Over-flags (13 unmatched MLGG flags)

- `model_selection_audit_gate` (severity MEDIUM, cat `model_selection`)
  - Evidence: We tested the known CNNs, such as VGG16, ResNET V1 and V2, Inception V1-V4, Mobilenet, etc., and found that InceptionV3 achieved most consistent results on many datasets. Please, do not use 'etc'. Be specific which ones were used. You stat...
- `leakage_gate` (severity CRITICAL, cat `data_leakage`)
  - Evidence: A significant methodological issue: the use of the same dataset for both GWAS and PPS parameterisation. This overlap will result in overfitting of PPS and optimism in performance estimates. This is clearly demonstrated by the drop in perfo...
- `leakage_gate` (severity CRITICAL, cat `data_leakage`)
  - Evidence: Possible data leakage in UK Biobank phenotype evaluation — many phenotypes are correlated. Since authors trained on both simulated and real data, held-out test phenotypes may overlap with training set.
- `cohort_definition_gate` (severity HIGH, cat `study_design`)
  - Evidence: Although the revised manuscript shows in detail the comparison between previous models and the proposed ones, it still remains unclear which model, out of the Tri AI-segment, Tri AI-severity, and Tri RR is the final suggested model to use...
- `sample_size_gate` (severity HIGH, cat `sample_size`)
  - Evidence: Derivation/validation cohorts smaller than claimed; no prospective power analysis presented per setting; refitting six-gene signature across ED vs ICU vs multi-country cohorts risks tuning leakage.
- `cohort_definition_gate` (severity HIGH, cat `study_design`)
  - Evidence: The author has described that only 183,021 participants with GP records were included in the trained machine learning models. I was wondering whether the author used the same sub-population to run genetic analyses with regenie. If yes, hav...
- `evaluation_quality_gate` (severity HIGH, cat `evaluation_metrics`)
  - Evidence: Model Validation: The adjusted R² is reported at 0.31. It would be beneficial for the authors to compare this with other models beyond the Mayo Imaging Classification to contextualize whether an R² of 0.31 is considered robust.
- `external_validation_gate` (severity HIGH, cat `external_validation`)
  - Evidence: TriNetX dataset was selected for the external validation in this study. A significant concern about this study is the generalizability. The model performance on this external dataset seems not optimal (even the author explained the missing...
- `model_selection_audit_gate` (severity HIGH, cat `model_selection`)
  - Evidence: Analytical approach is outdated and simplistic — many publications already describe similar strategies with much more advanced deep learning methods. Authors must show (i) PPI-guided selection beats unguided penalized regression, (ii) drug...
- `external_validation_gate` (severity HIGH, cat `external_validation`)
  - Evidence: The most novel aspect of this work is the adjMMD and its strong association with decrement in AUC. However, the experiments performed thus far are not convincing regarding its association with the change in AUC. More experiments should be...
- `evaluation_quality_gate` (severity HIGH, cat `evaluation_metrics`)
  - Evidence: Genetic-centric and genetic-imaging analyses used different statistical approaches. Is AUC comparison fair with different model types? Over 100 imaging variables makes clinical applicability questionable.
- `model_selection_audit_gate` (severity HIGH, cat `model_selection`)
  - Evidence: Why did you choose DQN, and why did you modify it to ignore states? Please discuss this on a more mathematical level, because no justification is given in the text. Have you compared this to other methods? Random forests? Support vector ma...
- `evaluation_quality_gate` (severity HIGH, cat `evaluation_metrics`)
  - Evidence: While there seems to be an improvement of the predictive performance of the NetBio model when compared to other transcriptomic features (PD1, PD-L1, etc.), the achieved values are generally rather low. This is even more worrying, as the nu...

## Narrative

PR-EXP-0084 is a deliberate stress test: 15 reviewer concerns is roughly double the PR-EXP-batch average, and the KB extraction note flags Reviewer #1 as unusually thorough with significant unresolved methodological gaps after Round 2. The RAG-only pipeline recovers 7/15 concerns (recall 0.55, weighted F1 0.484) with every match landing on the `exact_code` tier — the post-67f7492 fix is doing exactly the work it was shipped for, since each missed match here would otherwise have collapsed to the dead `concern_id` path. The recall gap is concentrated in MEDIUM-severity concerns (7/10 missed) tied to gates that are either rare in the KB (`shap_interpretability_gate`, `feature_lineage_gate`, `fairness_equity_gate`, `covariate_shift_gate`, `publication_gate`) or that the synthesized query failed to surface against KB-frequent neighbours; the lone HIGH miss (C07, VAE-justification) is a methods-rationale concern with no clean MLGG analogue. Over-flagging is the other story: 13/20 retrieved flags are off-topic exemplars (genomics, CNN benchmarks, NetBio, DQN, GWAS — evidence the query is broad enough to drag in adjacent corpora), which drops weighted precision to 0.43 once severity-discounted. Two over-flags carry CRITICAL severity (both `leakage_gate` on GWAS/UKB phenotypes) — they are not wrong KB entries, just wrong matches for *this* paper, and per-severity shows zero CRITICAL miss/match because the paper has no CRITICAL concerns. Headline takeaway for the recall stress test: doubling concern count exposes a MEDIUM-tier coverage cliff, not a HIGH/CRITICAL failure, and the matcher's lexical-only fast path stays well-calibrated when the embedding tier is offline.
