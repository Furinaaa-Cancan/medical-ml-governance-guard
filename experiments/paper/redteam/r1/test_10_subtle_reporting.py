"""Red Team #10 (VERY HARD): Multiple subtle reporting issues, no code-level leakage."""
import pandas as pd
import numpy as np
from sklearn.model_selection import GroupShuffleSplit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

df = pd.read_csv("icu_mortality.csv")
X = df.drop(columns=["patient_id", "died_in_icu"])
y = df["died_in_icu"]

groups = df["patient_id"]
gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
train_idx, test_idx = next(gss.split(X, y, groups))

X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

model = LogisticRegression(max_iter=1000, random_state=42)
model.fit(X_train, y_train)

y_prob = model.predict_proba(X_test)[:, 1]
auroc = roc_auc_score(y_test, y_prob)
y_pred = (y_prob >= 0.5).astype(int)  # BUG: hardcoded 0.5 threshold, not optimized

# BUG: only AUROC reported — no AUPRC, no calibration, no CI, no DCA
# BUG: single model only — no comparison with ≥3 families
# BUG: no random seed stability check
# BUG: no subgroup analysis
print(f"AUROC: {auroc:.4f}")
print("Model is ready for clinical deployment.")  # BUG: overstatement
