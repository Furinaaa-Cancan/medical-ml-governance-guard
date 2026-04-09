"""Red Team R3 #24: Data snooping via visualization — analyst sees test distribution
before building model, biasing feature engineering decisions."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("data.csv")
X = df.drop(columns=["outcome"])
y = df["outcome"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# BUG: Analyst looks at test set distribution before deciding on feature engineering
print("=== TEST SET EXPLORATION (data snooping) ===")
print(f"Test positive rate: {y_test.mean():.4f}")
print(f"Test feature means:\n{X_test.mean()}")
print(f"Test feature correlations with outcome:\n{X_test.corrwith(y_test).sort_values()}")

# Now makes feature engineering decisions based on what they saw in test set
# This is human-in-the-loop leakage — impossible for lint to detect
X_train["age_squared"] = X_train["age"] ** 2  # "inspired" by test correlation
X_test["age_squared"] = X_test["age"] ** 2

model = GradientBoostingClassifier(random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
