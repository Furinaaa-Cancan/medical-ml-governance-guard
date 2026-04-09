"""Red Team R2 #19: LabelEncoder used on nominal feature (race) for LR."""
import pandas as pd
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

df = pd.read_csv("ehr_data.csv")

# BUG: LabelEncoder on nominal variable 'race' — imposes false ordinal structure
le = LabelEncoder()
df["race_encoded"] = le.fit_transform(df["race"])  # Caucasian=0, Asian=1, Black=2...

X = df[["age", "bmi", "race_encoded", "num_visits"]]
y = df["readmitted"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
scaler = StandardScaler()
X_train = scaler.fit_transform(X_train)
X_test = scaler.transform(X_test)

model = LogisticRegression(max_iter=1000, random_state=42)
model.fit(X_train, y_train)
y_prob = model.predict_proba(X_test)[:, 1]
print(f"AUROC: {roc_auc_score(y_test, y_prob):.4f}")
