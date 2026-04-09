"""Red Team R3 #27: Subtle future feature — 'days_to_next_visit' only known after outcome."""
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("outpatient.csv")

features = [
    "age", "sex", "bmi", "hba1c_baseline",
    "num_prior_hospitalizations",
    "days_since_last_visit",
    "days_to_next_visit",       # BUG: this is FUTURE info — only known after follow-up
    "medication_adherence_pct",  # BUG: adherence over follow-up period includes post-outcome time
    "total_healthcare_cost",     # BUG: total cost includes costs incurred AFTER the event
]

X = df[features]
y = df["hospitalized_within_90d"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
print(f"Brier: {brier_score_loss(y_test, y_prob):.4f}")
