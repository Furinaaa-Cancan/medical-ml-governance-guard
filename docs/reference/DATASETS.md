# Datasets Reference (16 Real Medical Datasets)

> 16 real-world medical datasets totaling 630K+ rows ship in `examples/*.csv` and drive
> MLGG's end-to-end gate test suite. Each dataset has a known leakage trap or modelling
> pitfall that exercises specific gates. All data comes from official institutions
> (CDC / UCI / NCI-NIH / Vanderbilt / Framingham) — no patient-identifiable rows are
> bundled and no registration is required for the public-release copies.

## Quick links

- Back to [README (CN)](../../README.md) | [README (EN)](../../README_EN.md)
- Forward refs (under construction by parallel sessions): `GATES.md`, `MODEL_FAMILIES.md`, `LINT_RULES.md`
- Coverage source of truth: [`references/operations/dataset-gate-coverage-matrix.md`](../../references/operations/dataset-gate-coverage-matrix.md)
- Variable codebook: [`references/codebooks/dataset-codebook-registry.json`](../../references/codebooks/dataset-codebook-registry.json)

## What "16 datasets" means here

The number tracks the CSV count under `examples/`:

```
examples/breast_cancer.csv                examples/heart_disease.csv
examples/brfss2022_aligned.csv            examples/nci_gdc_cancer_survival.csv
examples/brfss2022_diabetes.csv           examples/nhanes_diabetes.csv
examples/chronic_kidney_disease.csv       examples/nhis2022_diabetes.csv
examples/covid19_hospitalization.csv      examples/pima_diabetes.csv
examples/diabetes130_full_readmission.csv examples/rhc_icu_mortality.csv
examples/diabetes_130_readmission.csv     examples/sepsis_survival.csv
examples/framingham_heart.csv             examples/support2.csv
```

Two BRFSS variants (`brfss2022_aligned`, `brfss2022_diabetes`) and two Diabetes-130
variants (full + compact) are counted separately because each carries a different
column schema and exercises a different gate slice.

## Summary table

Counts come from `references/operations/dataset-gate-coverage-matrix.md` for the
seven datasets it lists; the remaining nine entries are derived from the CSV
schema and download scripts. "Exercises gates" lists the most representative gates
each dataset is wired to trip — not the full coverage cell.

| # | Dataset (CSV stem) | Source | Rows | Cols (predictors) | Target | Modality | Known leakage trap | Exercises gates |
|---:|---|---|---:|---:|---|---|---|---|
| 1 | `diabetes130_full_readmission` | UCI | 101,766 | 16 | 30-day readmission | Diabetes EHR | `discharge_disposition_id`, `number_inpatient`, `number_emergency` post-index | leakage_gate (L01), definition_variable_guard (F01), feature_lineage_gate (F03), split_protocol_gate (S01) |
| 2 | `diabetes_130_readmission` | UCI (compact) | ~10,000 | 16 | 30-day readmission | Diabetes EHR | same trap surface as #1, smaller sample for fast CI | leakage_gate, calibration_dca_gate, model_selection_audit_gate |
| 3 | `nhanes_diabetes` | CDC NHANES 2017-2020 | ~16,000 | 15 | Undiagnosed diabetes | Survey + lab | `LBXGH` (HbA1c) and `LBXGLU` (fasting glucose) are the *definition* variables — must_exclude_if_target. `DIQ160`/`DIQ170` doctor-told-you fields are target-adjacent. Survey weights (`WTMEC2YR`) MUST NOT enter as features. | definition_variable_guard, cohort_definition_gate (C01), leakage_gate, fairness_equity_gate |
| 4 | `nhis2022_diabetes` | CDC NHIS 2022 | ~28,000 | 17 | Self-reported diabetes | Household survey | Diagnosis-adjacent insurance / utilization items; no lab values (telephone survey only) | cohort_definition_gate, fairness_equity_gate, calibration_dca_gate |
| 5 | `brfss2022_diabetes` | CDC BRFSS 2022 | ~100,000 | 14 | `DIABETE4` self-report | Telephone survey | `DIABETE4` itself is the target; `BPHIGH6`, `TOLDHI3`, `CVDSTRK3` are reverse-causation hazards for diabetes prediction | leakage_gate, definition_variable_guard, fairness_equity_gate |
| 6 | `brfss2022_aligned` | CDC BRFSS 2022 (schema-aligned to NHIS) | ~100,000 | 14 | Self-reported diabetes | Telephone survey | Cross-source schema alignment exposes covariate-shift bugs vs `nhis2022_diabetes` | covariate_shift_gate, leakage_gate |
| 7 | `nci_gdc_cancer_survival` | NCI / NIH GDC | ~25,000 | 18 | 2-year survival post-diagnosis | Cancer registry | `vital_status`, `days_to_death` are outcome-derived; `treatment_*` are post-index; cancer stage at diagnosis is borderline (acceptable as baseline feature, not as post-treatment) | leakage_gate, feature_lineage_gate, definition_variable_guard, calibration_dca_gate |
| 8 | `sepsis_survival` | UCI Sepsis Survival Minimal | ~129,000 | 3 | Hospital-discharge survival | Minimal EHR | Only 3 predictors (age, sex, episode_number) — exercises *small-feature-set* gate paths, NOT the rich-feature ones | split_protocol_gate, basic leakage_gate; coverage ~12/31 (C-tier per coverage matrix) |
| 9 | `rhc_icu_mortality` | Vanderbilt RHC (Connors 1996) | 5,735 | 54 | 180-day mortality | ICU EHR | RHC catheter use (`swang1`) is the *exposure* in original causal study — treating it as predictor mixes causal and predictive roles. `dth30` derivatives leak the target window. | leakage_gate, feature_lineage_gate, definition_variable_guard, calibration_dca_gate (29/31 A-tier) |
| 10 | `support2` | Vanderbilt SUPPORT2 | 9,105 | 43 | In-hospital / 6-month mortality | ICU EHR | `surv2m`, `surv6m`, `prg2m`, `prg6m` are *doctor's prognostic estimates* — these are model competitors, not features. `aps`, `sps`, `avtisst` are severity-of-illness scores computed from same admission. | leakage_gate, definition_variable_guard, calibration_dca_gate, model_selection_audit_gate (29/31 A-tier) |
| 11 | `covid19_hospitalization` | CDC COVID-19 Case Surveillance | ~100,000 | 3 | Hospitalization | Public health surveillance | Only 3 predictors; *temporal split required* (case dates span pandemic waves); race/ethnicity high-missingness → fairness gate sensitivity | split_protocol_gate (temporal mode), fairness_equity_gate, covariate_shift_gate (C-tier 12/31) |
| 12 | `framingham_heart` | Framingham Heart Study (public teaching extract) | ~4,200 | 15 | 10-year CHD | Cohort | `prevalentHyp`, `prevalentStroke`, `diabetes` overlap with downstream events — temporal eligibility check needed. `BPMeds` is treatment-conditional. | leakage_gate, cohort_definition_gate, feature_lineage_gate |
| 13 | `breast_cancer` | UCI WDBC | 569 | 30 | Malignant vs benign | Imaging-derived tabular | All 30 features are mean/SE/worst of the *same 10 nuclei measures* — high collinearity; small N exercises sample-size and overfitting gates | sample_size_gate, leakage_gate (collinearity branch), calibration_dca_gate (26/31 B-tier) |
| 14 | `chronic_kidney_disease` | UCI CKD | 399 | 24 | CKD diagnosis | Tabular labs | Diagnosis-defining labs (`sc` creatinine, `bu` urea) are the *definition* variables → must_exclude_if_target. `pcv`/`hemo` measured at same visit as outcome label. Imputation-before-split is the classic failure mode on this dataset. | definition_variable_guard, leakage_gate (imputation branch), F01 (target-as-feature) (26/31 B-tier) |
| 15 | `heart_disease` | UCI Cleveland | 297 | 13 | Angiographic disease (target binarised) | Tabular | `oldpeak`, `slope`, `ca`, `thal` come from the *same angiogram* that defines the label — they leak unless you frame the task as "predict from pre-angiogram features only" | leakage_gate, definition_variable_guard, sample_size_gate (22/31 B-tier) |
| 16 | `pima_diabetes` | UCI Pima Indian (Smith 1988) | 768 | 8 | Diabetes (oral glucose 2hPG > 200) | Tabular | `Glucose` IS the target threshold value — text-book leakage trap. Zero-coded missingness in `SkinThickness`, `Insulin`, `BloodPressure` exercises imputation-sensitivity gate. | definition_variable_guard, leakage_gate, mnar_sensitivity (21/31 B-tier; smallest end-to-end testable case) |

Total: ~630K rows. A/B-tier datasets (11) sustain 21–29 of the 31 end-to-end-testable
gates; C-tier datasets (3 — `sepsis_survival`, `covid19_hospitalization`,
`brfss2022_aligned` if treated alone) only exercise ~12 gates because their schema
is too thin for the cohort / feature-lineage / fairness branches.

## Per-dataset detail

The sections below expand the four datasets that have a published codebook entry
in `references/codebooks/dataset-codebook-registry.json`. The other twelve are
documented at the summary-table level; promotion to long-form lives on the
backlog and should land alongside formal fixture metadata.

### diabetes130_full_readmission (UCI Diabetes 130-US Hospitals)

- **Source**: UCI Machine Learning Repository, dataset 296 (Strack 2014, *BioMed Research International*)
- **Rows / cols**: 101,766 admissions / 16 predictor columns (CSV total = predictors + `patient_id` + `event_time` + `y`)
- **Target**: 30-day readmission (binary; positive = `readmitted == '<30'`)
- **Patient grain**: One row per admission, multiple admissions per patient — `patient_nbr` must drive the group split (S01)
- **Known leakage traps**:
  - `discharge_disposition_id`: only known at discharge → leaks for readmission task
  - `number_inpatient`, `number_emergency`, `number_outpatient`: when computed using the index admission they encode post-index utilisation
  - `time_in_hospital`: length-of-stay overlaps with the prediction window
  - `A1Cresult` and `max_glu_serum` are double-role — definition-adjacent for diabetes severity, but legitimate as predictors of readmission *if* measured at admission
- **Gates exercised**: leakage_gate, definition_variable_guard, feature_lineage_gate, split_protocol_gate, cohort_definition_gate, calibration_dca_gate, model_selection_audit_gate (29/31 A-tier)
- **Downloader**: `python3 examples/download_real_data.py diabetes130_full`
- **Out of scope**: HbA1c trajectory modelling (this is cross-sectional admission data, not a longitudinal signal)
- **Reference implementation**: `examples/demo_diabetes130/` end-to-end pipeline

### nhanes_diabetes (CDC NHANES 2017-2020 Pre-Pandemic)

- **Source**: CDC / NCHS, 2017–2020 Pre-Pandemic cycle (`P_*` files)
- **Rows / cols**: ~16,000 participants / 15 predictor columns
- **Target**: Undiagnosed diabetes (composite from `LBXGH`, `LBXGLU`, `DIQ010` per ADA criteria)
- **Design**: stratified multistage cluster, survey-weighted
- **Known leakage traps** (see codebook for full list):
  - `LBXGH` (HbA1c %), `LBXGLU` (fasting glucose): definition variables — `must_exclude_if_target`
  - `DIQ010`, `DIQ160`, `DIQ170`, `DIQ172`: doctor-told-you fields — target-adjacent
  - `LBXTC` / `LBDHDD` / `LBXTR`: same-visit labs → post-prediction state when target is diabetes
  - Reverse-causation risk: `MCQ160C` (CHD), `MCQ160F` (stroke) — DM→CVD pathway means using these to predict DM may capture reverse causation
  - Survey weights (`WTMEC2YR`) MUST be passed to estimators as sample weights, not features (R028-adjacent operational rule)
- **Quirks**: `RIDAGEYR` top-coded at 80; 2019–2020 cycle truncated by COVID-19
- **Gates exercised**: definition_variable_guard, cohort_definition_gate, leakage_gate, fairness_equity_gate, calibration_dca_gate (29/31 A-tier)
- **Downloader**: `python3 examples/download_nhanes.py --cycles both`
- **Codebook**: 21 variables Harvard-validated (`references/codebooks/nhanes/`); cross-check rate 21/21, 0 semantic conflicts (last validated 2026-04-10)

### brfss2022_diabetes (CDC BRFSS 2022)

- **Source**: CDC Behavioral Risk Factor Surveillance System 2022
- **Rows / cols**: ~100,000 respondents / 14 predictor columns
- **Target**: `DIABETE4 == 1` (ever told you have diabetes; gestational and pre-diabetes coded separately)
- **Design**: stratified random-digit-dial telephone survey; survey-weighted
- **Known leakage traps**:
  - `DIABETE4` is the target — its raw and re-coded variants must be tracked through feature lineage
  - `BPHIGH6`, `TOLDHI3`, `CVDSTRK3`: comorbidity self-report — reverse-causation hazards for diabetes prediction (codebook flags `reverse_causation_risk: [diabetes]`)
  - `_BMI5`: BMI × 100 — divide-by-100 transform is a common silent bug; self-reported height/weight bias the values low
  - No lab values (no glucose, HbA1c, lipids) and no BP readings (only self-reported diagnosis) — limits feature-engineering scope
- **Gates exercised**: leakage_gate, definition_variable_guard, fairness_equity_gate, model_selection_audit_gate (25/31 B-tier)
- **Downloader**: `python3 examples/download_cdc_data.py brfss`

### support2 (Vanderbilt SUPPORT II)

- **Source**: SUPPORT II prognostic study (Knaus 1995 / Connors 1996), Vanderbilt Biostatistics public release
- **Rows / cols**: 9,105 ICU admissions / 43 predictor columns
- **Target**: In-hospital mortality OR 6-month mortality (project-dependent)
- **Known leakage traps**:
  - `surv2m`, `surv6m`, `prg2m`, `prg6m`: physician-elicited survival probability estimates — these are *baseline competitors* (the human prognosis to beat), not features
  - `aps`, `sps`: APACHE / SUPPORT physiology scores computed from same admission — using them as features collapses the model to "predict severity from severity"
  - `avtisst`, `totcst`, `totmcst`, `hospdead`: resource-use and outcome-derived columns that leak
  - `dnr`, `dnrday`: DNR status flips during admission — temporal eligibility check needed
- **Gates exercised**: leakage_gate, definition_variable_guard, calibration_dca_gate, model_selection_audit_gate, fairness_equity_gate (29/31 A-tier)
- **Pre-bundled**: yes — `examples/support2.csv`

### rhc_icu_mortality (Vanderbilt RHC / Connors 1996)

- **Source**: Vanderbilt Biostatistics public release of the Connors et al. *JAMA* 1996 right-heart-catheterisation study
- **Rows / cols**: 5,735 ICU admissions / 54 predictor columns (richest feature set in the bundled fixtures)
- **Target**: 180-day mortality (`dth30` / `death` derivatives must be re-derived from `dthdte − sadmdte`)
- **Known leakage traps**:
  - `swang1` is the *exposure* of interest in the original causal paper (RHC use yes/no). Reusing it as a predictor mixes the propensity-score role with the prediction role — flag in feature lineage.
  - `dth30`, `dthdte`, `lstctdte`: outcome-derived; absence is itself informative (censoring → MNAR)
  - `t3d30`, `dschdte`: discharge / 30-day time markers — overlap with the prediction window
  - `aps1`, `surv2md1`, `meanbp1` carry the index-day suffix — verify the `_1` truly means day 1 and not "summary across stay"
- **Gates exercised**: leakage_gate, feature_lineage_gate, definition_variable_guard, calibration_dca_gate, model_selection_audit_gate, fairness_equity_gate (29/31 A-tier; richest schema in the suite)
- **Downloader**: `python3 examples/download_real_data.py rhc`

### pima_diabetes (UCI Pima Indian)

- **Source**: UCI ML Repository; original from Smith et al. 1988 (National Institute of Diabetes / Kaggle mirror)
- **Rows / cols**: 768 women aged 21+ / 8 predictor columns — the smallest end-to-end-testable fixture
- **Target**: Diabetes (oral glucose tolerance test 2-hour plasma glucose ≥ 200 mg/dL)
- **Known leakage traps**:
  - `Glucose` IS the threshold used to define the label — text-book F01 (target as feature). Most public notebooks miss this because the label column is renamed `Outcome`.
  - `Insulin`, `SkinThickness`, `BloodPressure`, `BMI`: zeros encode *missing*, not zero — silent fillna(0) corrupts distributions and feeds the imputation-sensitivity gate
  - N=768 with prevalence ≈ 35% → exercises `sample_size_gate` (Riley-EPV guidance, see [21 Analysis Tools](../../README_EN.md#21-analysis-tools))
- **Gates exercised**: definition_variable_guard (F01), leakage_gate, mnar_sensitivity, sample_size_gate (21/31 B-tier)
- **Downloader**: `python3 examples/download_real_data.py pima`

## Leakage-pattern × dataset cross-index

Each row is a leakage *pattern* from `references/methodology/leakage-taxonomy.md`;
columns are the datasets that visibly carry the trap and so are useful regression
fixtures for that pattern. `–` means the schema does not surface the pattern (not
that the dataset is clean; only that this particular trap cannot fire here).

| Leakage pattern | Datasets that exhibit it |
|---|---|
| Target-as-feature (F01) | `pima_diabetes` (`Glucose`), `nhanes_diabetes` (`LBXGH`/`LBXGLU`/`DIQ010`), `brfss2022_diabetes` (`DIABETE4` re-encodes), `chronic_kidney_disease` (`sc`/`bu`), `heart_disease` (`oldpeak`/`thal` from same angiogram) |
| Post-index / post-outcome features (L01) | `diabetes130_full_readmission` (`discharge_disposition_id`, `time_in_hospital`), `nci_gdc_cancer_survival` (`vital_status`, `treatment_*`), `support2` (`hospdead`, `totcst`), `rhc_icu_mortality` (`dth30`, `t3d30`) |
| Same-visit measurement bundling (F03) | `nhanes_diabetes` (`LBXTC`/`LBDHDD`/`LBXTR` same-visit as `LBXGH`), `support2` (APS computed from admission labs), `breast_cancer` (mean/SE/worst of the same 10 nuclei measures) |
| Reverse causation (causal direction inverted) | `nhanes_diabetes` (CHD/stroke → diabetes), `brfss2022_diabetes` (`CVDSTRK3`/`TOLDHI3`), `framingham_heart` (`prevalentHyp`/`prevalentStroke` overlap with 10-year CHD endpoint) |
| Definition-variable leak (target embedded in eligibility) | `nhanes_diabetes`, `chronic_kidney_disease`, `pima_diabetes`, `heart_disease`, `support2` (severity scores collapse with outcome) |
| Temporal split required (random split misleads) | `covid19_hospitalization` (pandemic waves), `diabetes130_full_readmission` (encounter dates), `nci_gdc_cancer_survival` (diagnosis-year cohorts) |
| Imputation-before-split (P01) | `chronic_kidney_disease` (heavy missingness in `pcv`/`hemo`/`pcc`), `pima_diabetes` (zero-coded missing), `framingham_heart` (`glucose`/`BPMeds` missing) |
| Exposure-vs-predictor confusion | `rhc_icu_mortality` (`swang1`), `support2` (`dnr` is partly treatment), `diabetes130_full_readmission` (`insulin`/`change`/`diabetesMed` flips are treatment, not baseline) |
| Survey-weight misuse | `nhanes_diabetes` (`WTMEC2YR`), `nhis2022_diabetes`, `brfss2022_*` (`_LLCPWT`) — weights are sample weights for estimators, never features |
| Small-N overfitting (Riley/EPV) | `heart_disease` (N=297), `chronic_kidney_disease` (N=399), `breast_cancer` (N=569), `pima_diabetes` (N=768), `framingham_heart` (N≈4.2K with rare event) |

## Dataset-to-gate coverage matrix

Authoritative figures live in
[`references/operations/dataset-gate-coverage-matrix.md`](../../references/operations/dataset-gate-coverage-matrix.md).
Tiering summary:

| Tier | Datasets | Gate coverage | Use |
|---|---|---|---|
| A | diabetes130_full, nhis2022, nci_gdc, nhanes, diabetes_130 (10K), support2, rhc | 29/31 (94%) | End-to-end validation, publication-grade rehearsals |
| B | brfss2022 (both variants), breast_cancer, chronic_kidney_disease, heart_disease, pima_diabetes | 21–26/31 (68–84%) | Per-gate testing, small-N or limited-schema scenarios |
| C | sepsis_survival, covid19_hospitalization | 12/31 (39%) | Baseline gate paths only — DO NOT claim full validation |

`framingham_heart` is not tiered in the matrix; treat it as B-tier pending formal scoring.

**Gates not testable on any bundled dataset**: `external_validation_gate` (no
paired external cohort ships) and `reporting_bias_gate` (needs a human-filled
TRIPOD+AI checklist, not a data artefact).

## Data ethics note

MLGG bundles **public-release** copies of these datasets only. None contains
direct patient identifiers; the CDC/UCI/Vanderbilt/NCI public releases have
already been de-identified per HIPAA Safe Harbor or equivalent statutory
process at source. Two operational consequences:

- The 18-pattern PHI scan in `scripts/core/_security.py` still runs over any
  user-supplied CSV; bundled examples pass clean.
- Original ICU / EHR sources behind some of these public extracts (MIMIC-III/IV,
  eICU-CRD, UK Biobank) require *credentialed access* — those datasets are NOT
  bundled, only referenced in the codebook registry for column-semantic lookup.

If you replace any of the 16 fixtures with a credentialed pull (e.g. swapping
the SUPPORT2 public extract for the full PhysioNet variant), re-run
`mlgg audit` and the cohort_definition_gate before committing — schema drift
between public-release and credentialed copies is common.

## Related

- [`docs/reference/`](.) sibling docs (under construction): `GATES.md`, `MODEL_FAMILIES.md`, `LINT_RULES.md`
- [`references/codebooks/dataset-codebook-registry.json`](../../references/codebooks/dataset-codebook-registry.json) — variable-level semantics for NHANES / BRFSS / MIMIC-IV / UK Biobank
- [`references/codebooks/nhanes/`](../../references/codebooks/nhanes/) — Harvard CCB-HMS 58K-variable validated codebook
- [`references/operations/dataset-gate-coverage-matrix.md`](../../references/operations/dataset-gate-coverage-matrix.md) — authoritative tier source
- [`references/methodology/leakage-taxonomy.md`](../../references/methodology/leakage-taxonomy.md) — Kapoor 8-type leakage classification this doc maps to

## Changelog

- 2026-05-17: Initial reference (W12-B3). Sourced from `examples/*.csv`,
  `dataset-codebook-registry.json` (v1.1), and `dataset-gate-coverage-matrix.md`
  (v1.0). Twelve datasets documented at summary-table depth; four (diabetes130,
  nhanes, brfss2022, support2) expanded to long-form using the codebook registry.
