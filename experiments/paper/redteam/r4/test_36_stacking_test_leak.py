"""Red Team R4 #36: Stacking ensemble where base model predictions on test
are used to train the meta-learner, then evaluated on the same test set."""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("data.csv")
X = df.drop(columns=["outcome"])
y = df["outcome"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Base models — correctly trained on train
m1 = RandomForestClassifier(n_estimators=100, random_state=42).fit(X_train, y_train)
m2 = GradientBoostingClassifier(random_state=42).fit(X_train, y_train)

# BUG: meta-features from TEST set used to TRAIN the meta-learner
meta_test = np.column_stack([
    m1.predict_proba(X_test)[:, 1],
    m2.predict_proba(X_test)[:, 1],
])

# BUG: meta-learner trained on test set predictions, then evaluated on same test set
meta_model = LogisticRegression(max_iter=1000)
meta_model.fit(meta_test, y_test)  # BUG: fitting on test!
y_prob = meta_model.predict_proba(meta_test)[:, 1]

print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
