"""Red Team R2 #16: Temporal data shuffled in train_test_split."""
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("longitudinal_ehr.csv")
# admission_date column exists — this is temporal data
X = df.drop(columns=["patient_id", "admission_date", "readmitted_30d"])
y = df["readmitted_30d"]

# BUG: shuffle=True (default) on temporal data — future data leaks into training
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, shuffle=True
)

model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
