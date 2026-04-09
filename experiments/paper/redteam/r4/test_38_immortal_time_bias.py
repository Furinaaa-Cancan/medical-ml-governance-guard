"""Red Team R4 #38: Immortal time bias — treatment group requires surviving long enough
to receive treatment, creating artificial survival advantage."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("drug_study.csv")

# BUG: "received_drug_x" requires the patient to survive to day 7 (drug initiation)
# Patients who died before day 7 are all in the "no drug" group
# This creates immortal time bias — the drug group has guaranteed 7-day survival
features = [
    "age", "sex", "baseline_sofa",
    "received_drug_x",  # BUG: immortal time bias
    "baseline_creatinine", "baseline_lactate",
]

X = df[features]
y = df["died_28d"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = LogisticRegression(max_iter=1000, random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
