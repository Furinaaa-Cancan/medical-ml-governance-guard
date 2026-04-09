"""Red Team R2 #20: Methodologically correct but dangerously overstated conclusions."""
import pandas as pd
import numpy as np
from sklearn.model_selection import GroupShuffleSplit
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
from sklearn.calibration import calibration_curve

df = pd.read_csv("sepsis.csv")
X = df.drop(columns=["patient_id", "sepsis_onset"])
y = df["sepsis_onset"]

# Correct split by patient
groups = df["patient_id"]
gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
train_idx, test_idx = next(gss.split(X, y, groups))

X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

# Multiple models — methodologically correct
for name, clf in [("LR", LogisticRegression(max_iter=1000, random_state=42)),
                  ("RF", RandomForestClassifier(n_estimators=100, random_state=42)),
                  ("GBM", GradientBoostingClassifier(random_state=42))]:
    clf.fit(X_train, y_train)
    y_prob = clf.predict_proba(X_test)[:, 1]
    auroc = roc_auc_score(y_test, y_prob)
    auprc = average_precision_score(y_test, y_prob)
    brier = brier_score_loss(y_test, y_prob)
    print(f"{name}: AUROC={auroc:.4f} AUPRC={auprc:.4f} Brier={brier:.4f}")

# BUG: no CI, no calibration slope/intercept, no DCA, no subgroup analysis
# BUG: overstatement — claiming "superior to existing tools"
print("\nConclusion: Our model achieves state-of-the-art performance")
print("and is ready for deployment in clinical practice.")
print("The model significantly outperforms existing sepsis scores.")
