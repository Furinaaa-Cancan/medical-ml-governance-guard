"""Red Team #7 (HARD): HbA1c used as feature to predict diabetes — definition leakage."""
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

df = pd.read_csv("nhanes_data.csv")

# Diabetes defined as: HbA1c >= 6.5 OR fasting_glucose >= 126 OR self_report == 1
df["diabetes"] = ((df["hba1c"] >= 6.5) | (df["fasting_glucose"] >= 126) |
                  (df["self_report_diabetes"] == 1)).astype(int)

features = ["age", "bmi", "systolic_bp", "total_cholesterol", "hdl",
            "hba1c", "fasting_glucose",  # BUG: definition variables used as features
            "smoking_status", "physical_activity", "family_history"]

X = df[features]
y = df["diabetes"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)
print(f"AUROC: {roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]):.4f}")
# Will show AUROC ~0.99 due to perfect leakage
