# GOOD: OrdinalEncoder for features, LabelEncoder only for target
from sklearn.preprocessing import OrdinalEncoder
import pandas as pd

df = pd.read_csv("data.csv")
encoder = OrdinalEncoder()
df[["gender", "department"]] = encoder.fit_transform(df[["gender", "department"]])
