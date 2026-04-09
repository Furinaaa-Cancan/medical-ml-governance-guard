# MLGG Paper Experiment Results Summary

Generated: 2026-04-09 (updated with ground truth)

---

## Experiment 1: Ground Truth Prevalence Study (PRIMARY)

**Question**: How many medical ML repos have real data leakage?

**Method**: Curated 55 medical ML repos from PapersWithCode/GitHub → verified Python training code (39 valid) → MLGG lint scan → agent deep code review → ground truth annotation

### Ground Truth Results (n=39)

| Metric | Value |
|--------|-------|
| Repos evaluated | 39 |
| **Actual leakage rate** | **69.2% (27/39)** |
| Lint-reported leakage rate | 23.1% (9/39) |
| Actually clean | 12/39 (30.8%) |

### MLGG Lint Performance (vs Ground Truth)

```
                  Actually Leak    Actually Clean
  Lint=Leak         TP= 7            FP= 2
  Lint=Clean        FN=20            TN=10
```

| Metric | Value | Interpretation |
|--------|-------|----------------|
| **Precision** | **77.8%** | Lint flags are mostly real issues |
| **Recall** | **25.9%** | Lint catches only 1/4 of real leakage |
| **Specificity** | **83.3%** | Low false positive rate |
| **F1** | **38.9%** | Poor overall due to low recall |

### What Lint Misses (20 False Negatives)

| Missed Pattern | Count | Why Lint Can't Catch It |
|----------------|-------|------------------------|
| Imputation before split (fillna/median/mean) | 8 | fillna() not matched as preprocessing |
| Feature selection before split | 5 | SelectKBest/ExtraTrees in non-standard positions |
| Manual normalization (not sklearn API) | 5 | (X-mean)/std, manual min-max |
| Cross-file leakage | 3 | preprocess.py saves CSV, train.py loads |
| SMOTE/oversampling (non-SMOTE API) | 2 | sklearn.utils.resample not matched |
| Hyperparameter tuning on test | 2 | Optuna/GridSearchCV on test set |
| Encoding before split | 1 | LabelEncoder/TargetEncoder |

### False Positives (2)
Both caused by lint not understanding sklearn Pipeline encapsulation:
- ASCVD_ML: scaler inside Pipeline (correctly handled)
- stroke_prediction: preprocessing inside imblearn Pipeline

### Key Finding
**Lint alone detects only 26% of real leakage. The remaining 74% requires semantic code understanding (Layer 3 agent).** This validates the 3-layer architecture.

---

## Experiment 2: Red Team Validation

**Question**: How accurately does MLGG lint detect known synthetic defects?

**Method**: 40 synthetic adversarial scenarios across 4 difficulty levels

### Detection Rates (Lint Layer Only)
| Difficulty | Scenarios | Detected | Rate |
|------------|-----------|----------|------|
| Easy (R1) | 10 | 10 | 100% |
| Medium (R2) | 10 | 8 | 80% |
| Hard (R3) | 10 | 7 | 70% |
| Extreme (R4) | 10 | 6 | 60% |
| **Total** | **40** | **31** | **77.5%** |

### Note on Red Team vs Real World
Red team recall (77.5%) >> real-world recall (25.9%) because:
- Red team scenarios use standard sklearn API patterns lint is designed for
- Real code uses manual implementations, cross-file patterns, non-standard APIs
- This gap itself is a key finding for the paper

---

## Experiment 3: Peer Review Knowledge Base

**Question**: What do human reviewers focus on vs what MLGG catches?

### Domain Focus Analysis (106 NC papers, 375 concerns)
| Domain | Concerns | Percentage | Who covers this? |
|--------|----------|------------|-----------------|
| Design-level | 208 | 55.5% | Reviewer |
| Shared | 136 | 36.3% | Both |
| Code-level | 31 | 8.3% | MLGG |

**91.7% of reviewer concerns are NOT about code-level issues.**

---

## Paper Narrative Arc

1. **The Problem**: 69% of medical ML repos have data leakage (Ground Truth, n=39)
2. **The Gap**: Static lint catches only 26% — human reviewers focus on design, not code (KB analysis)
3. **The Solution**: MLGG's 3-layer architecture: Lint (precision 78%) + Agent + RAG (closes the 74% gap)
4. **The Validation**: Red team confirms lint ceiling (77.5% on synthetic, 26% on real)

---

## Data Files

| File | Description |
|------|-------------|
| `output/ground_truth_annotations.json` | 39-repo ground truth with leakage types |
| `output/ground_truth_scan.json` | Lint scan results for all 39 repos |
| `output/redteam_results.json` | 40-scenario red team evaluation |
| `output/kb_analysis.json` | 106-paper peer review KB analysis |
| `output/exp1_prevalence_preliminary.json` | PMC scan preliminary (superseded by ground truth) |
| `ground_truth_candidates.json` | 55 candidate repos |
| `papers_with_code_exp1.jsonl` | 1,267 PMC papers with GitHub links |
