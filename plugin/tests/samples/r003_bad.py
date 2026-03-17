# BAD: SMOTE on test data
from imblearn.over_sampling import SMOTE
from sklearn.model_selection import train_test_split
import pandas as pd

df = pd.read_csv("data.csv")
X = df.drop(columns=["target"])
y = df["target"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

sm = SMOTE()
X_test_res, y_test_res = sm.fit_resample(X_test, y_test)  # <-- leakage
