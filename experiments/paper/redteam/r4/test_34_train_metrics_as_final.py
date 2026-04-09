"""Red Team R4 #34: Reports train metrics as if they were test metrics via copy-paste error."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("data.csv")
X = df.drop(columns=["outcome"])
y = df["outcome"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

model = GradientBoostingClassifier(random_state=42)
model.fit(X_train, y_train)

# BUG: computes predictions on TRAIN but variable named y_prob_test
y_prob_test = model.predict_proba(X_train)[:, 1]  # BUG: X_train not X_test!

print("=== Test Set Results ===")  # Misleading header
print(f"AUROC: {roc_auc_score(y_train, y_prob_test):.4f}")  # BUG: y_train not y_test
print(f"AUPRC: {average_precision_score(y_train, y_prob_test):.4f}")
print(f"Brier: {brier_score_loss(y_train, y_prob_test):.4f}")
