"""Red Team R2 #12: Temporal oracle — full-stay features predict in-ICU mortality."""
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("mimic_icu.csv")

features = [
    "age", "gender", "admission_source",         # admission-time: OK
    "sofa_score_admission",                       # admission-time: OK
    "total_ventilation_hours",                    # BUG: measured over ENTIRE stay
    "max_vasopressor_dose",                       # BUG: max during stay
    "total_fluid_balance_ml",                     # BUG: cumulative during stay
    "num_blood_cultures",                         # BUG: ordered during stay
    "last_lactate",                               # BUG: last measurement, not first
    "apache_ii_score",                            # OK if computed at admission
]

X = df[features]
y = df["died_in_icu"]

groups = df["subject_id"]
gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
train_idx, test_idx = next(gss.split(X, y, groups))

model = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)
model.fit(X.iloc[train_idx], y.iloc[train_idx])
y_prob = model.predict_proba(X.iloc[test_idx])[:, 1]
print(f"AUROC: {roc_auc_score(y.iloc[test_idx], y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y.iloc[test_idx], y_prob):.4f}")
print(f"Brier: {brier_score_loss(y.iloc[test_idx], y_prob):.4f}")
