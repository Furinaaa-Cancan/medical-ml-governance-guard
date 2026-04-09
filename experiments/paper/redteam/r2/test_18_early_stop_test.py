"""Red Team R2 #18: XGBoost early stopping on test set."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
from xgboost import XGBClassifier

df = pd.read_csv("data.csv")
X_train, X_test, y_train, y_test = train_test_split(
    df.drop(columns=["outcome"]), df["outcome"], test_size=0.2, random_state=42
)

model = XGBClassifier(
    n_estimators=1000,
    learning_rate=0.05,
    max_depth=4,
    eval_metric="logloss",
    early_stopping_rounds=50,
    random_state=42,
)
# BUG: eval_set uses TEST data — early stopping leaks test info into training
model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
