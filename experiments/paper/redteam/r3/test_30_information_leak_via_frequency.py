"""Red Team R3 #30: Information leakage via frequency encoding on full data."""
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("claims.csv")

# BUG: Frequency encoding computed on FULL data before split
# Rare categories in test set get different frequencies if computed on train only
for col in ["diagnosis_code", "procedure_code", "provider_id"]:
    freq = df[col].value_counts(normalize=True)
    df[col + "_freq"] = df[col].map(freq)  # BUG: full-data frequencies

df = df.drop(columns=["diagnosis_code", "procedure_code", "provider_id", "patient_id"])
X = df.drop(columns=["readmitted"])
y = df["readmitted"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
