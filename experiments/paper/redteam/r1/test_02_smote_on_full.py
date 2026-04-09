"""Red Team #2: SMOTE applied before split."""
import pandas as pd
from sklearn.model_selection import train_test_split
from imblearn.over_sampling import SMOTE

df = pd.read_csv("diabetes.csv")
X = df.drop(columns=["y"])
y = df["y"]

sm = SMOTE(random_state=42)
X_res, y_res = sm.fit_resample(X, y)  # BUG: SMOTE on full data

X_train, X_test, y_train, y_test = train_test_split(X_res, y_res, test_size=0.2)
