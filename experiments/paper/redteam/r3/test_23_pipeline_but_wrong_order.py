"""Red Team R3 #23: Pipeline used correctly, but SMOTE placed AFTER classifier.
Looks correct (Pipeline!) but SMOTE should be before the classifier."""
import pandas as pd
from sklearn.model_selection import cross_val_score
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline

df = pd.read_csv("data.csv")
X = df.drop(columns=["outcome"])
y = df["outcome"]

# BUG: SMOTE after classifier — nonsensical but Pipeline doesn't catch it
pipe = Pipeline([
    ("scaler", StandardScaler()),
    ("model", LogisticRegression(max_iter=1000, random_state=42)),
    ("smote", SMOTE(random_state=42)),  # BUG: wrong position
])

scores = cross_val_score(pipe, X, y, cv=5, scoring="roc_auc")
print(f"CV AUROC: {scores.mean():.4f} ± {scores.std():.4f}")
