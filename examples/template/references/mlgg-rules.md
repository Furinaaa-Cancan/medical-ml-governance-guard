# MLGG Rules Quick Reference

## Data Leakage Taxonomy

Six types of leakage in predictive pipelines:

| Type | Description | Red Flag |
|------|-------------|----------|
| **Split Contamination** | Identical/near-identical samples across train/test | Duplicate rows, copy-paste augmentation |
| **Group Leakage** | Same entity (patient) appears across splits | `train_test_split` without `groups=` |
| **Temporal Look-Ahead** | Using future information at prediction time | Discharge features for admission prediction |
| **Target Proxy** | Features that directly encode the outcome | Diagnosis codes from same encounter |
| **Preprocessing Leakage** | fit() on full data before split | `scaler.fit(X)` before `train_test_split` |
| **Imputation Leakage** | Imputer stats from test/combined data | `SimpleImputer().fit(X_all)` |

## Common Anti-patterns

| Pattern | Severity | What's Wrong |
|---------|----------|--------------|
| `scaler.fit(X)` then split | CRITICAL | Scaler sees test distribution |
| `SMOTE(X, y)` then split | CRITICAL | Synthetic samples leak into test |
| `SelectKBest(X, y)` then split | CRITICAL | Feature selection sees test labels |
| `df.dropna()` then split | CRITICAL | Missingness pattern leaked |
| `model.fit(X, y, eval_set=test)` | CRITICAL | Early stopping on test data |
| `threshold = roc_curve(y_test)` | CRITICAL | Threshold optimized on test |
| `accuracy_score` on imbalanced | WARNING | Misleading metric |
| No `random_state=` | INFO | Not reproducible |

## Correct Patterns

```python
# Correct: split by patient ID first (MLGG-S01)
from sklearn.model_selection import GroupShuffleSplit

gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
train_idx, test_idx = next(gss.split(X, y, groups=patient_ids))
X_train, X_test = X[train_idx], X[test_idx]
y_train, y_test = y[train_idx], y[test_idx]

# Then fit on train only
scaler = StandardScaler()
X_train = scaler.fit_transform(X_train)   # fit on train
X_test = scaler.transform(X_test)          # transform only

# Correct: SMOTE on train only
smote = SMOTE(random_state=42)
X_train_res, y_train_res = smote.fit_resample(X_train, y_train)
# X_test is NEVER resampled

# Correct: threshold on validation set
fpr, tpr, thresholds = roc_curve(y_valid, y_valid_prob)
optimal_idx = np.argmax(tpr - fpr)  # Youden's J
threshold = thresholds[optimal_idx]
# Apply to test set
y_test_pred = (y_test_prob >= threshold).astype(int)
```

## Literature References

| Topic | Reference | Key Finding |
|-------|-----------|-------------|
| SMOTE & calibration | van den Goorbergh 2022 (JAMIA) | SMOTE harms probability calibration |
| Feature selection | Heinze 2018, Harrell 2015 | Univariate pre-screening deprecated |
| Stability selection | Meinshausen & Buhlmann 2010 | prob > 0.6 threshold |
| Sample size | Riley 2019/2020 | Shrinkage >= 0.9 criterion |
| Calibration | Van Calster 2019 | Slope + intercept + O/E "triple" |
| MCC vs F1 | Chicco & Jurman 2020 | MCC more informative for imbalanced |
| Model selection | Yang et al. KDD 2023 | Select by validation, not train-test gap |
| Internal validation | Steyerberg 2019, Harrell 2015 | Bootstrap optimism correction |
| Missingness | Madley-Dowd 2019, Sperrin 2020 | Mechanism > proportion |
| TRIPOD+AI | BMJ 2024;385:e078378 | 27-item reporting checklist |
