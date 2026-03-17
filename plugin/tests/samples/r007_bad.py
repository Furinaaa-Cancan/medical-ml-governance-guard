# BAD: same variable for X and y in model.fit
from sklearn.ensemble import RandomForestClassifier
import pandas as pd

df = pd.read_csv("data.csv")

clf = RandomForestClassifier()
clf.fit(df, df)  # same variable for features and target
