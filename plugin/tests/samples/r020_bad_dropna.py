# BAD: dropna on full data before split
import pandas as pd
from sklearn.model_selection import train_test_split

df = pd.read_csv("data.csv")
df = df.dropna()  # <-- leakage: global missingness pattern
X = df.drop(columns=["target"])
y = df["target"]
X_train, X_test, y_train, y_test = train_test_split(X, y)
