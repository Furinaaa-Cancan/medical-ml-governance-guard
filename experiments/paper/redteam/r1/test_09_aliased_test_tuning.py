"""Red Team #9 (VERY HARD): Test set used for tuning via variable aliasing."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

df = pd.read_csv("data.csv")
X = df.drop(columns=["patient_id", "outcome"])
y = df["outcome"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# BUG: "holdout" is actually test set, used for tuning
holdout_X = X_test
holdout_y = y_test

best_auroc = 0
best_params = None
for n_est in [50, 100, 200, 500]:
    for depth in [3, 5, 7, 10]:
        model = RandomForestClassifier(n_estimators=n_est, max_depth=depth, random_state=42)
        model.fit(X_train, y_train)
        auroc = roc_auc_score(holdout_y, model.predict_proba(holdout_X)[:, 1])
        if auroc > best_auroc:
            best_auroc = auroc
            best_params = {"n_estimators": n_est, "max_depth": depth}

print(f"Best AUROC: {best_auroc:.4f}")  # BUG: this IS test performance, optimistically biased
