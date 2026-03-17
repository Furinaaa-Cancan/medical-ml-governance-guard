# BAD: split without groups in patient data
from sklearn.model_selection import train_test_split
import pandas as pd

df = pd.read_csv("patient_data.csv")
patient_id = df["patient_id"]
X = df.drop(columns=["patient_id", "target"])
y = df["target"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
