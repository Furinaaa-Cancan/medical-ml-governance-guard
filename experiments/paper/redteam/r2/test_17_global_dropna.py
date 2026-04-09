"""Red Team R2 #17: Global dropna before split — loses patients non-randomly."""
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("clinical_data.csv")

# BUG: dropna on full data before split — MNAR rows removed globally
df = df.dropna()

X = df.drop(columns=["patient_id", "mortality"])
y = df["mortality"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = LogisticRegression(max_iter=1000, random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
