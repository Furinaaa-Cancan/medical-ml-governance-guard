# MLGG Paper Experiment Results Summary

Generated: 2026-04-10 (v7 final: strict + lenient evaluation, methodology verified)

---

## Experiment 1: Ground Truth Prevalence Study (PRIMARY)

**Question**: How many medical ML repos have real data leakage?

**Method**: Curated 55 medical ML repos from PapersWithCode/GitHub → verified Python training code (40 with annotations, 1 excluded: empty repo id=27 with no code to evaluate → **39 valid**) → MLGG lint scan → agent deep code review → ground truth annotation

### Ground Truth Results (n=39)

| Metric | Value |
|--------|-------|
| Repos evaluated | 39 |
| **Actual leakage rate** | **69.2% (27/39)** |
| Actually clean | 12/39 (30.8%) |

### MLGG Lint Performance

#### Repo-level evaluation (lenient)

A repo is TP if lint flags leakage AND the repo actually has leakage,
regardless of whether the specific finding matches the actual leakage type.

| Metric | V1 (baseline) | V6 (final) |
|--------|---------------|------------|
| TP | 7 | **22** |
| FP | 2 | **3** |
| FN | 20 | **5** |
| TN | 10 | **9** |
| **Precision** | 77.8% | **88.0%** |
| **Recall** | 25.9% | **81.5%** |
| **F1** | 38.9% | **84.6%** |
| **Specificity** | 83.3% | **75.0%** |

#### Finding-level evaluation (strict)

A repo is TP only if the specific lint finding correctly identifies a
real leakage pattern. 3 "coincidental TPs" are reclassified as FN:
repos where lint flagged a non-leaking pattern but the repo has leakage
for a different reason that lint missed.

| Metric | Lenient | Strict | Δ |
|--------|---------|--------|---|
| TP | 22 | **19** | −3 |
| FP | 3 | **3** | 0 |
| FN | 5 | **8** | +3 |
| TN | 9 | **9** | 0 |
| **Precision** | 88.0% | **86.4%** | −1.6pp |
| **Recall** | 81.5% | **70.4%** | −11.1pp |
| **F1** | 84.6% | **77.6%** | −7.0pp |

#### Coincidental TP details

A coincidental TP is a repo where lint flags a non-leaking pattern, but the
repo has real leakage for a *different* reason that lint missed entirely.

| ID | Repo | Lint Finding | Real Leakage (missed by lint) | Why Coincidental |
|----|------|-------------|-------------------------------|-----------------|
| 24 | Early-Prediction-of-Sepsis | R002: labelencoder.fit_transform(Y_test) | oversampling_before_split (sklearn resample on full data) | R002 flagged benign label reshape on fresh encoder — not actual leakage |
| 26 | sepsis-early-detection | R003: SMOTE before cross_validate | imputer/scaler fit_transform on val/test independently | SMOTE is after custom split_data(); lint misidentified cross_validate as split boundary. Real leak is imputer/scaler refit on test — a different issue entirely |
| 50 | MIRAGE | R020: dropna() before split | Optuna objective evaluates on test set; cross_val_score on full X,y | dropna doesn't learn statistics (debatable as leakage); real leaks are hyperparameter tuning on test and CV on full data |

### V1 → V6 Improvement Breakdown

Verified by re-running V1/V6 scans and tracing each new TP to its root cause.

| Fix | Type | TP gained | Details |
|-----|------|-----------|---------|
| Notebook IPython magic stripping | Infra fix | **+8** | id=11,16,21,24,38,40,49,54 — V1 returned E000 parse error, V6 parses successfully |
| R020 severity WARNING→ERROR | Rule fix | **+4** | id=29,45,50,55 — R020 fired at WARNING in V1 (not counted), ERROR in V6 |
| R027 manual scaling before split | New rule | **+1** | id=15 — manual (X-min)/(max-min) normalization detected |
| R011 added to leakage_rules | Eval fix | **+1** | id=28 — SMOTE+CV without imblearn.Pipeline |
| Cross_val fallback split detection | Enhancement | **+1** | id=26 — cross_validate as fallback split marker |
| Subscript unwrap (train_test_split(...)[0]) | Bug fix | 0 | Correctness fix, no new TPs in this dataset |
| String .split() guard | Bug fix | 0 | Prevented FP on for-loop .split() |
| R026 fillna before split | New rule | **0** | R026 never fires alone — all R026 repos also have R020. Adds specificity to diagnostics but no unique TPs |
| **Total** | | **+15** | |

Note: R026 provides more specific diagnostic messages (e.g., "fillna(median())
before split") vs R020's generic "global statistics leak". It is valuable for
user guidance even though it doesn't increase repo-level detection count.

### What Lint Still Misses (strict: 8 False Negatives)

| Category | Count | Repos | Why Missed |
|----------|-------|-------|-----------|
| Coincidental TP (reclassified) | 3 | Early-Prediction-of-Sepsis (id=24), sepsis-early-detection (id=26), MIRAGE (id=50) | Lint flagged a non-leaking pattern; real leakage is a different issue lint can't detect |
| Cross-file leakage | 2 | readmission_prediction (id=10), CKD-Prediction (id=36) | Preprocessing in file A, split in file B — lint is single-file |
| Cross-file + borderline | 1 | Chronic-Kidney-Disease (id=37) | dropna() in preprocess.py before split — borderline: dropna doesn't learn statistics |
| Notebook taint limitation | 1 | stroke-prediction-machine-learning (id=31) | fillna+scaler in notebook; lint can't track cross-cell taint |
| No split at all | 1 | Tumor-Prediction-with-ML (id=34) | DEG+RFE on full data, trained and evaluated on same data — no split to detect |

### False Positives (3)

| Repo | Rule | Why FP | Notes |
|------|------|--------|-------|
| ASCVD_ML (id=19) | R001/R002 | Preprocessing inside sklearn Pipeline — correctly handled per-fold | Clear FP |
| stroke_prediction (id=30) | R001 | Preprocessing inside imblearn Pipeline — correctly handled per-fold | Clear FP |
| wids-datathon-2021 (id=22) | R020/R026 | fillna(median) on concat(train+test) before internal split | **Judgment call**: technically IS leakage (global statistics), but competition context where train+test boundary is the organizer's, not the modeler's. If reclassified as TP: precision 92%, FP=2 |

### Key Finding

**V1 lint detects 26% of real leakage. V6 reaches 70-82% (strict-lenient range) with 86-88% precision.** The remaining 8 strict false negatives break down as: coincidental TPs where lint flagged the wrong thing (3/8), cross-file leakage across script boundaries (2-3/8), notebook taint limitations (1/8), and no-split repos (1/8). Cross-file and semantic patterns require Layer 3 agent analysis.

#### Sensitivity analysis (annotation judgment calls)

Two annotations involve judgment calls that affect metrics:
- **id=22 (wids-datathon)**: FP in current annotation (competition context). If reclassified as TP: strict precision 92.0% (+5.6pp), FP=2.
- **id=37 (Chronic-Kidney-Disease)**: TP in current annotation (borderline dropna). If reclassified as not-leakage: prevalence 66.7% (−2.5pp), strict FN=7.

Neither changes the qualitative conclusions.

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

1. **The Problem**: 69% of medical ML repos have data leakage (n=39; sensitivity: 67-69% depending on borderline dropna classification)
2. **The Gap**: V1 lint catches only 26%; human reviewers focus on design (55.5%), not code (8.3%)
3. **The Improvement**: Targeted rules + infra fixes raise strict recall to 70% (lenient 82%)
4. **The Transparency**: 3/22 repo-level TPs are coincidental (strict precision 86%, lenient 88%); 1 FP is a judgment call (competition context) — if reclassified, precision rises to 92%
5. **The Ceiling**: Coincidental TPs (3/8 FN), cross-file patterns (2-3/8), and no-split repos (1/8) are lint's hard boundary
6. **The Complementarity**: MLGG finds code issues reviewers miss; reviewers find design issues MLGG can't

---

## Technical Fixes Applied (V1→V6)

| Fix | File | Impact |
|-----|------|--------|
| Strip IPython magics | `plugin/mlgg_lint/notebook.py` | 5 notebooks parseable |
| Strip get_ipython() calls | `plugin/mlgg_lint/notebook.py` | nbconvert compatibility |
| Raise .ipynb size limit to 5MB | `experiments/paper/scan_published_repos.py` | 1 large notebook scanned |
| Unwrap Subscript in taint | `plugin/mlgg_lint/engine.py` | train_test_split(...)[0] detected |
| Cross_val as fallback split marker | `plugin/mlgg_lint/engine.py` | CV-only files detected |
| String .split() guard | `plugin/mlgg_lint/engine.py` | Prevent FP on string parsing |
| R026 fillna before split | `plugin/mlgg_lint/rules/r026_fillna_before_split.py` | New rule |
| R027 manual scaling | `plugin/mlgg_lint/rules/r027_manual_scaling_before_split.py` | New rule |
| R020 severity → ERROR | `plugin/mlgg_lint/rules/r020_global_clean_before_split.py` | Severity fix |

---

## Data Files

| File | Description |
|------|-------------|
| `output/ground_truth_annotations.json` | 39-repo ground truth with leakage types |
| `output/ground_truth_scan.json` | V1 lint scan results |
| `output/ground_truth_scan_v6.json` | V6 lint scan results (final) |
| `output/redteam_results.json` | 40-scenario red team evaluation |
| `output/kb_analysis.json` | 106-paper peer review KB analysis |
| `ground_truth_candidates.json` | 55 candidate repos |
