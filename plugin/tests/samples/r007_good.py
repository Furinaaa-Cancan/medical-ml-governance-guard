# GOOD: target column dropped before training
from sklearn.ensemble import RandomForestClassifier
import pandas as pd

df = pd.read_csv("data.csv")
X = df.drop(columns=["target"])
y = df["target"]

clf = RandomForestClassifier()
clf.fit(X, y)
