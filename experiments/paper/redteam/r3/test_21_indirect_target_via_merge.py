"""Red Team R3 #21: Label leaks through a merge — df2 contains outcome info joined back."""
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("patients.csv")
outcomes = pd.read_csv("outcomes.csv")  # has patient_id + died + discharge_date

# BUG: merge brings in "died" column, then "died" is used to create a derived feature
df = df.merge(outcomes[["patient_id", "died", "los"]], on="patient_id")
df["high_risk_ward"] = df.groupby("ward")["died"].transform("mean")  # target encoding via merge
df["label"] = df["died"]

X = df.drop(columns=["patient_id", "died", "label", "ward"])
y = df["label"]
# "high_risk_ward" is still in X — indirect label leakage through merge + groupby

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = LogisticRegression(max_iter=1000, random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
print(f"AUPRC: {average_precision_score(y_test, y_prob):.4f}")
