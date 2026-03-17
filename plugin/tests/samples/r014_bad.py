# BAD: LabelEncoder on feature columns
from sklearn.preprocessing import LabelEncoder
import pandas as pd

df = pd.read_csv("data.csv")
le = LabelEncoder()
df["gender"] = le.fit_transform(df["gender"])
df["department"] = le.fit_transform(df["department"])
