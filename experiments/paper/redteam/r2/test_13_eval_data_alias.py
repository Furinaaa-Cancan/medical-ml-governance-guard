"""Red Team R2 #13: Test set aliased to 'eval_data' — does R021 catch non-standard names?"""
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

df = pd.read_csv("data.csv")
X_train, X_test, y_train, y_test = train_test_split(
    df.drop(columns=["outcome"]), df["outcome"], test_size=0.2, random_state=42
)

# BUG: eval_data is X_test under a different name — R021 won't catch "eval_data"
eval_data = X_test
eval_labels = y_test

best = 0
for d in [3, 5, 7]:
    m = RandomForestClassifier(max_depth=d, random_state=42)
    m.fit(X_train, y_train)
    s = roc_auc_score(eval_labels, m.predict_proba(eval_data)[:, 1])  # BUG: tuning on test
    if s > best:
        best = s
print(f"Best: {best:.4f}")
