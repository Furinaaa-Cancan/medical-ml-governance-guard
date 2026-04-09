"""Red Team R3 #29: Survival outcome forced into binary — ignores censoring."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("cancer_survival.csv")

# BUG: Censored patients (alive at last follow-up) treated as "survived"
# This is wrong — censored ≠ survived. Patients lost to follow-up are NOT negative cases.
# Should use survival analysis (Cox model) instead of binary classification.
df["died_5yr"] = (df["survival_months"] <= 60).astype(int)
# Patients with survival_months=24 and status="censored" are coded as died_5yr=1
# even though they were lost to follow-up at 24 months, not dead.

features = ["age", "stage", "grade", "tumor_size", "lymph_nodes_positive",
            "er_status", "pr_status", "her2_status"]
X = df[features]
y = df["died_5yr"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = GradientBoostingClassifier(random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
