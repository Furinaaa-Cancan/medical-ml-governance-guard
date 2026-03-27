# Systematic Review Protocol: Prevalence of Data Leakage in Published Medical ML Prediction Studies with Public Code

**Protocol Version**: 1.0
**Date**: 2026-03-26
**Pre-registration**: To be registered on OSF (osf.io) before screening begins

---

## 1. Review Question

**Primary question**: What proportion of published medical ML clinical prediction studies with publicly available Python code contain detectable data leakage?

**Secondary questions**:
- What types of leakage are most prevalent (taxonomy: Kapoor & Narayanan 2023)?
- Is there a temporal trend in leakage prevalence (2015–2025)?
- Does leakage prevalence differ by journal tier, disease area, or model type?
- What is the quantitative impact of detected leakage on reported performance?

## 2. Study Design

**Type**: Cross-sectional methodological study with systematic search (not a traditional intervention systematic review, but following PRISMA 2020 reporting where applicable)

**Two-phase design** (following JAMA Network Open 2025 precedent):
- **Phase 1 (Automated, broad)**: Automated MLGG lint scan of all eligible repos (N≈200+)
- **Phase 2 (Manual, deep)**: Full manual audit of stratified random subsample (N=50) using Kapoor 8-type taxonomy

This gives both a large-n automated prevalence estimate AND a detailed manual audit.

## 3. Eligibility Criteria

### 3.1 Inclusion Criteria (all must be met)

| # | Criterion | Rationale |
|---|-----------|-----------|
| I1 | Original research article (not review, editorial, commentary, letter, protocol, meta-analysis) | Only primary studies have auditable methods |
| I2 | Develops or validates a clinical prediction/classification model | Scope: prediction modeling, not descriptive or causal inference |
| I3 | Uses structured/tabular clinical data (EHR, registry, claims, biobank, public clinical dataset) | MLGG lint operates on tabular ML pipelines |
| I4 | Binary or multi-class classification outcome | Scope limitation; survival analysis excluded |
| I5 | Publicly available Python source code (GitHub, GitLab, Zenodo, Bitbucket, or supplementary files) | Code must be auditable by MLGG lint |
| I6 | Code contains model training logic (data splitting, model fitting, evaluation) | Repos with only data processing or visualization are not auditable |
| I7 | Published 2015-01-01 to 2025-12-31 in a peer-reviewed journal | 10-year window covering sklearn popularization through present |
| I8 | Full text available in English | Practical language constraint |

### 3.2 Exclusion Criteria (any one sufficient)

| # | Criterion | Rationale |
|---|-----------|-----------|
| E1 | Code is in R, Julia, MATLAB, SAS, or other non-Python language only | MLGG lint supports Python only |
| E2 | Repository is a general-purpose framework/library (e.g., scikit-learn, XGBoost, MIMIC-code) rather than paper-specific implementation | Not a paper's own code |
| E3 | Repository is empty, archived with no code, or download fails | Not auditable |
| E4 | Prediction target is image-based, text-based, or time-series signal (e.g., ECG waveform, chest X-ray, pathology slide) | Out of scope for tabular leakage detection |
| E5 | Study uses only pre-trained models without fine-tuning on clinical data | No training pipeline to audit |
| E6 | Code contains only Jupyter notebook with no executable Python (e.g., only markdown documentation) | Not parseable |
| E7 | Duplicate publication or same code repo used by multiple papers (keep only the first/primary) | Avoid double-counting |

## 4. Information Sources and Search Strategy

### 4.1 Databases

| Database | Coverage | Search method |
|----------|----------|---------------|
| **PubMed/MEDLINE** | Biomedical journals | MeSH + free text |
| **PubMed Central (PMC)** | Open-access full text | Full-text search for code URLs |
| **Embase** (via Ovid) | Broader biomedical + engineering | Emtree + free text |
| **Web of Science** | Multidisciplinary | Topic search |
| **Scopus** | Broad scientific | Title/abstract/keyword |
| **IEEE Xplore** | Engineering/CS conferences | Full text |

### 4.2 Search Terms

**Concept 1 — Machine Learning**:
```
"machine learning" OR "deep learning" OR "artificial intelligence"
OR "random forest" OR "gradient boosting" OR "XGBoost" OR "LightGBM"
OR "neural network" OR "support vector machine" OR "logistic regression"
```

**Concept 2 — Clinical Prediction**:
```
"prediction model" OR "predictive model" OR "clinical prediction"
OR "risk prediction" OR "prognostic model" OR "diagnostic model"
OR "classification" OR "risk score" OR "risk stratification"
```

**Concept 3 — Clinical/Medical Setting**:
```
"patient" OR "clinical" OR "hospital" OR "electronic health record"
OR "EHR" OR "cohort" OR "registry" OR "medical" OR "healthcare"
```

**Concept 4 — Code Availability** (for PMC full-text only):
```
"github.com" OR "gitlab.com" OR "zenodo.org" OR "code availability"
OR "source code" OR "code repository"
```

**Combined**: (Concept 1) AND (Concept 2) AND (Concept 3)
**For PMC**: Add AND (Concept 4) for initial broad screening

**Filters**: Publication date 2015-01-01 to 2025-12-31; English language; Article type: Journal Article

### 4.3 Supplementary Search

- **Forward/backward citation tracking** of Kapoor & Narayanan 2023
- **Papers With Code** (paperswithcode.com) — medical area, filtered for clinical prediction tasks
- **Manual search** of high-impact journals: Nature Medicine, JAMA, BMJ, Lancet Digital Health, npj Digital Medicine (table of contents 2015-2025)

## 5. Screening Process

### 5.1 De-duplication

Use Endnote/Zotero to de-duplicate across databases (automated + manual review of near-duplicates).

### 5.2 Title/Abstract Screening (Stage 1)

- **Tool**: Rayyan (rayyan.ai) — free, supports blinded dual screening
- **Reviewers**: 2 independent reviewers
- **Blinding**: Enabled (each reviewer cannot see the other's decisions)
- **Pilot**: First 100 records screened by both reviewers with discussion to calibrate criteria
- **Decision**: Include / Exclude / Uncertain
- **Conflict resolution**: Discussion → consensus; if unresolved, 3rd reviewer
- **Report**: Cohen's kappa for inter-rater agreement

### 5.3 Full-Text + Code Screening (Stage 2)

- **Reviewers**: 2 independent reviewers
- **Process for each paper**:
  1. Read full text, confirm prediction model study (I1-I4, I7-I8)
  2. Locate code availability statement, extract repo URL
  3. Verify repo exists and is downloadable
  4. Verify repo contains Python training code (I5-I6)
  5. Verify repo corresponds to THIS paper (not a general tool) (E2)
  6. Confirm tabular/structured data, not imaging/NLP (E4)
  7. Check for duplicate repos (E7)
- **Decision**: Include (with verified repo URL) / Exclude (with reason code)
- **Report**: Cohen's kappa, PRISMA flow diagram

### 5.4 Expected Yield

Based on Navarro et al. 2022 (24,814 → 152) and our PMC pilot (300 → 343 with GitHub):

| Stage | Expected N |
|-------|-----------|
| Database search results (combined) | ~50,000-80,000 |
| After de-duplication | ~30,000-40,000 |
| After title/abstract screening | ~3,000-5,000 |
| After full-text screening | ~500-1,000 (prediction model studies) |
| With public Python code | ~200-400 |
| After code verification | ~150-300 (final sample) |

**Target**: ≥200 papers (provides ±7% margin for prevalence estimate at 95% CI)

## 6. Data Extraction

### 6.1 Extraction Form (per paper)

**Bibliographic**: DOI, PMID, PMC ID, title, authors, journal, year, impact factor

**Study characteristics**:
- Disease area (cardiovascular, oncology, diabetes, ICU/sepsis, respiratory, kidney, neurology, other)
- Data source (single-center EHR, multicenter EHR, public dataset, registry, biobank)
- Sample size (total N, events, non-events, prevalence)
- Model type(s) used
- Number of candidate models
- Primary metric reported
- Reported AUROC (95% CI if available)
- External validation (yes/no)
- TRIPOD/PROBAST claimed (yes/no)

**Code characteristics**:
- Repository URL
- Language(s) (Python, mixed, notebook)
- Number of Python files
- Total lines of code
- Contains training logic (yes/no)
- Contains evaluation logic (yes/no)

### 6.2 Automated Audit (Phase 1)

Run `scan_published_repos.py` on each verified repo:
- MLGG lint findings (R001-R020): rule ID, severity, file, line
- Aggregate: has_leakage (any ERROR-level finding), leakage types found
- Per-rule counts

### 6.3 Manual Audit (Phase 2, subsample of 50)

**Sampling**: Stratified random sample from Phase 1 results:
- 25 papers flagged as "has leakage" by MLGG lint
- 25 papers flagged as "clean" by MLGG lint
- Stratified by journal tier and disease area

**Audit instrument**: Kapoor & Narayanan 8-type taxonomy:

| Code | Type | Manual check |
|------|------|-------------|
| L1.1 | No test set | Is there a held-out test set? |
| L1.2 | Preprocessing on full data | Is scaler/imputer fit only on train? |
| L1.3 | Feature selection on full data | Is feature selection done only on train? |
| L1.4 | Duplicates across splits | Are there row/patient duplicates? |
| L2 | Illegitimate features | Are post-index or proxy features used? |
| L3.1 | Temporal leakage | Is temporal ordering respected? |
| L3.2 | Non-independence | Are patients in only one split? |
| L3.3 | Sampling bias | Is test set representative? |

**Auditors**:
- Reviewer 1: MLGG lint automated static analysis (R001-R020)
- Reviewer 2: LLM-based code review (Claude) — independent line-by-line reading of source code, checking against Kapoor 8-type taxonomy without access to MLGG lint results
- Reviewer 3 (validation subset): Human domain expert reviews N=20 disagreement cases to establish ground truth

**Agreement metrics**:
- MLGG vs Claude: Cohen's kappa for inter-method reliability
- MLGG vs Human (on disagreement subset): precision/recall with human as reference standard
- Claude vs Human (on disagreement subset): validates Claude's reliability as reviewer

**Justification for LLM as reviewer**: Recent precedent in TRIPOD-LLM (Nature Medicine 2024) used LLM for checklist assessment. We validate LLM reliability against human expert on a subset.

**Report**: Per-type prevalence, inter-method kappa, MLGG sensitivity/specificity

## 7. Statistical Analysis

### 7.1 Primary Outcome

**Leakage prevalence** = N(papers with ≥1 ERROR-level MLGG finding) / N(total audited)
- Report with 95% Wilson confidence interval
- Subgroup analysis by: journal tier, year, disease area, model type, sample size

### 7.2 Temporal Trend

Logistic regression: leakage (binary) ~ year (continuous) + journal tier
- Test for monotonic trend
- Pre/post TRIPOD+AI 2024 comparison

### 7.3 MLGG Diagnostic Accuracy (Phase 2)

Against manual audit as reference standard:
- Sensitivity = TP / (TP + FN)
- Specificity = TN / (TN + FP)
- PPV, NPV
- Per-leakage-type sensitivity

### 7.4 Sample Size Justification

For estimating prevalence of 40% (based on JAMA 2025 ICD paper):
- 95% CI, margin of error ±7%: **N = 189**
- 95% CI, margin of error ±5%: **N = 369**

Target: ≥200 papers (achieves ±7% precision)

## 8. Risk of Bias

**For the review itself**: Use QUADAS-2 adapted for methodological reviews
- Domain 1: Paper selection (was sample representative?)
- Domain 2: Automated audit (MLGG lint: are the rules validated?)
- Domain 3: Manual audit (were auditors blinded to automated results?)
- Domain 4: Outcome definition (is "leakage" consistently defined?)

## 9. PRISMA Flow Diagram Template

```
┌─────────────────────────────────┐
│ Records identified (N=?)        │
│ PubMed: ?  Embase: ?  WoS: ?   │
│ Scopus: ?  IEEE: ?  PMC: ?     │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ After de-duplication (N=?)      │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ Title/abstract screened (N=?)   │──→ Excluded (N=?, reasons)
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ Full-text assessed (N=?)        │──→ Excluded (N=?, reasons:
└──────────────┬──────────────────┘    E1: non-Python
               ▼                        E2: framework/library
┌─────────────────────────────────┐    E3: empty/broken repo
│ Code verified (N=?)             │──→ E4: imaging/NLP
└──────────────┬──────────────────┘    E5: no training code
               ▼                        E6: not parseable
┌─────────────────────────────────┐    E7: duplicate)
│ Included in automated audit     │
│ Phase 1 (N≥200)                 │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ Stratified subsample for        │
│ manual audit Phase 2 (N=50)     │
└─────────────────────────────────┘
```

## 10. Timeline

| Week | Activity |
|------|----------|
| 1 | Pre-register protocol on OSF |
| 1-2 | Run database searches, export to Zotero |
| 2-3 | De-duplication |
| 3-6 | Title/abstract screening (Rayyan, dual) |
| 6-8 | Full-text + code screening (dual) |
| 8-9 | Data extraction + automated MLGG scan |
| 9-12 | Manual audit of subsample (N=50) |
| 12-14 | Statistical analysis |
| 14-18 | Manuscript writing |
| 18-20 | Internal review + submission |

## 11. Protocol Deviations

Any deviations from this protocol will be documented and reported in the final manuscript with justification.

## 12. References

1. Page MJ, et al. PRISMA 2020 statement. BMJ. 2021;372:n71
2. Kapoor S, Narayanan A. Leakage and the reproducibility crisis in ML-based science. Patterns. 2023;4(9):100804
3. JAMA Network Open 2025: Label leakage via ICD codes in MIMIC studies
4. Navarro CLA, et al. Completeness of reporting of clinical prediction models using ML. BMC Med Res Methodol. 2022;22:12
5. Collins GS, et al. TRIPOD+AI 2024. BMJ. 2024;385:e078378
6. Wolff RF, et al. PROBAST. Ann Intern Med. 2019;170(1):51-58
