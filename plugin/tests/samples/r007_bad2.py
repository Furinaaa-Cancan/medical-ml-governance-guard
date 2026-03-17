# BAD: X and y both from same df, X not via .drop()
from sklearn.ensemble import RandomForestClassifier
import pandas as pd

df = pd.read_csv("data.csv")
X = df[["col1", "col2", "col3"]]
y = df["target"]

clf = RandomForestClassifier()
clf.fit(X, y)  # X from df via subscript, y from df via subscript, no .drop()
