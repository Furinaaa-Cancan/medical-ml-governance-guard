# BAD: fillna with global mean before split
import pandas as pd
from sklearn.model_selection import train_test_split

df = pd.read_csv("data.csv")
df = df.fillna(df.mean())  # global mean leaks test info
X = df.drop(columns=["target"])
y = df["target"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
