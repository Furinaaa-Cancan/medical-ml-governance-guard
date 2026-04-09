"""Red Team R4 #39: Collider bias — conditioning on post-treatment variable
opens a non-causal path between treatment and outcome."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("cardiac.csv")

# BUG: Restrict cohort to patients who had cardiac catheterization
# Cath is a COLLIDER — influenced by both symptoms (predictor) and outcome (CAD)
# Conditioning on cath opens spurious path: symptoms ← cath → CAD
df = df[df["had_catheterization"] == 1]  # BUG: collider bias

features = ["age", "sex", "chest_pain_type", "resting_bp",
            "cholesterol", "fasting_bs", "resting_ecg", "max_hr",
            "exercise_angina", "st_depression"]
X = df[features]
y = df["obstructive_cad"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = GradientBoostingClassifier(random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
