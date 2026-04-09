"""Red Team R4 #35: Platt scaling fitted on test set — calibration leak."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("data.csv")
X = df.drop(columns=["outcome"])
y = df["outcome"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)
y_prob_raw = model.predict_proba(X_test)[:, 1]

# BUG: Platt scaling fitted on TEST data — uses test labels for calibration
platt = LogisticRegression(max_iter=1000)
platt.fit(y_prob_raw.reshape(-1, 1), y_test)  # BUG: fitting on test set!
y_prob_calibrated = platt.predict_proba(y_prob_raw.reshape(-1, 1))[:, 1]

print(f"AUROC: {roc_auc_score(y_test, y_prob_calibrated):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob_calibrated):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob_calibrated):.4f}")
