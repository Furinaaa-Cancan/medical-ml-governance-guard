"""Red Team #8 (HARD): Post-discharge features used for readmission prediction."""
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score

df = pd.read_csv("hospital_stays.csv")

features = [
    "age", "gender", "admission_type",  # admission-time: OK
    "num_prior_admissions",              # admission-time: OK
    "length_of_stay",                    # BUG: measured DURING hospitalization
    "num_procedures",                    # BUG: count of procedures during stay
    "discharge_disposition",             # BUG: determined at discharge
    "total_charges",                     # BUG: determined at discharge
    "num_medications_prescribed",        # BUG: prescribed during stay
]

X = df[features]
y = df["readmitted_30d"]  # outcome starts AFTER discharge

groups = df["patient_id"]
gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
train_idx, test_idx = next(gss.split(X, y, groups))

model = GradientBoostingClassifier(random_state=42)
model.fit(X.iloc[train_idx], y.iloc[train_idx])
y_prob = model.predict_proba(X.iloc[test_idx])[:, 1]
print(f"AUROC: {roc_auc_score(y.iloc[test_idx], y_prob):.4f}")
