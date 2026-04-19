"""Sample: Standard EHR tabular features — MLGG in scope."""
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

df = pd.read_csv("ehr_cohort.csv")
features = ["age", "sex", "bmi", "systolic_bp", "hba1c"]
X = df[features]
y = df["diabetes"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)
clf = RandomForestClassifier(random_state=42)
clf.fit(X_train, y_train)
