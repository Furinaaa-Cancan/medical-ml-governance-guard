"""Red Team R2 #14: Derived feature leakage — feature computed from label column."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("hospital.csv")

# BUG: ward_mortality_rate computed from the LABEL itself — target encoding leakage
df["ward_mortality_rate"] = df.groupby("ward")["died"].transform("mean")

features = ["age", "admission_type", "ward_mortality_rate", "num_comorbidities"]

X = df[features]
y = df["died"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = LogisticRegression(max_iter=1000, random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
