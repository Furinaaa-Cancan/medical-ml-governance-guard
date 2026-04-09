"""Red Team R4 #37: Conditional imputation using outcome-dependent logic."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("ehr.csv")

# BUG: impute missing labs differently based on outcome — target-dependent imputation
# "If patient died, missing creatinine is probably high (renal failure)"
# This encodes outcome knowledge into the imputed values
for col in ["creatinine", "bun", "lactate"]:
    died_median = df.loc[df["died"] == 1, col].median()
    alive_median = df.loc[df["died"] == 0, col].median()
    mask = df[col].isna()
    df.loc[mask & (df["died"] == 1), col] = died_median  # BUG: uses label
    df.loc[mask & (df["died"] == 0), col] = alive_median  # BUG: uses label

X = df.drop(columns=["patient_id", "died"])
y = df["died"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
