"""Red Team R2 #11: Definition leakage — eGFR defines CKD and is used as feature."""
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("kidney_cohort.csv")

# CKD defined as eGFR < 60 for ≥3 months
df["ckd"] = (df["egfr"] < 60).astype(int)

features = ["age", "sex", "bmi", "systolic_bp", "diastolic_bp",
            "egfr",  # BUG: eGFR defines the label — perfect leakage
            "albumin", "hemoglobin", "potassium", "phosphate",
            "diabetes_history", "hypertension_history"]

X = df[features]
y = df["ckd"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = GradientBoostingClassifier(random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
