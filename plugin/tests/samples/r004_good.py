# GOOD: split with groups for patient-level disjointness
from sklearn.model_selection import GroupShuffleSplit
import pandas as pd

df = pd.read_csv("patient_data.csv")
patient_id = df["patient_id"]
X = df.drop(columns=["patient_id", "target"])
y = df["target"]

gss = GroupShuffleSplit(n_splits=1, test_size=0.2)
train_idx, test_idx = next(gss.split(X, y, groups=patient_id))
