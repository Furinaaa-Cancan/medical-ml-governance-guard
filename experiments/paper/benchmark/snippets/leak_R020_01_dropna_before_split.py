from sklearn.model_selection import train_test_split
import pandas as pd
df = pd.read_csv("data.csv")
df = df.dropna()
X = df.drop(columns=["target"])
y = df["target"]
X_train, X_test, y_train, y_test = train_test_split(X, y)
