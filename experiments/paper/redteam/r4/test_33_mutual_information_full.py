"""Red Team R4 #33: Mutual information feature selection on full data.
Not SelectKBest — uses manual MI computation so R006 won't catch it."""
import pandas as pd
import numpy as np
from sklearn.feature_selection import mutual_info_classif
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("data.csv")
X = df.drop(columns=["patient_id", "outcome"])
y = df["outcome"]

# BUG: MI computed on FULL data before split — feature selection leak
mi_scores = mutual_info_classif(X, y, random_state=42)
top_k = 15
selected = np.argsort(mi_scores)[-top_k:]
X_selected = X.iloc[:, selected]

X_train, X_test, y_train, y_test = train_test_split(X_selected, y, test_size=0.2, random_state=42)
model = LogisticRegression(max_iter=1000, random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
