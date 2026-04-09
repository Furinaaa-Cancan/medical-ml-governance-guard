"""Red Team R4 #40: Informative censoring — sicker patients drop out of study,
making the remaining cohort look healthier than it is."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("longitudinal_hf.csv")

# BUG: Only patients with complete 1-year follow-up are included
# Patients who died or were too sick to return are excluded (informative censoring)
# This makes the cohort artificially healthy and the model artificially optimistic
df = df[df["follow_up_months"] >= 12]  # BUG: survivor bias / informative censoring

# BUG: Uses "improvement" as feature — but this is measured over the follow-up period
features = ["age", "sex", "lvef_baseline", "bnp_baseline",
            "nyha_class", "egfr_baseline",
            "showed_improvement",  # BUG: measured DURING follow-up
            "num_hospitalizations_prior_year"]
X = df[features]
y = df["died_1yr"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = LogisticRegression(max_iter=1000, random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
