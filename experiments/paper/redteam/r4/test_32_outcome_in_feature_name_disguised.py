"""Red Team R4 #32: Outcome encoded in a disguised feature name.
'discharge_status_3' is actually 'died in hospital' coded as category 3."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("ehr.csv")

# The outcome is 30-day mortality
df["died_30d"] = df["mortality_30d"]

features = [
    "age", "gender", "admission_type",
    "sofa_admission", "charlson_index",
    "discharge_status",  # BUG: discharge_status=3 means "expired" — encodes the outcome
    "icu_stay_hours",
    "mechanical_ventilation",
]

# One-hot encode — discharge_status_3 (expired) directly predicts mortality
df_encoded = pd.get_dummies(df[features], columns=["discharge_status"])
X = df_encoded
y = df["died_30d"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
