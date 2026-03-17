# BAD: feature selection before split
from sklearn.feature_selection import SelectKBest
from sklearn.model_selection import train_test_split
import pandas as pd

df = pd.read_csv("data.csv")
X = df.drop(columns=["target"])
y = df["target"]

selector = SelectKBest(k=10)  # <-- before split
X_selected = selector.fit_transform(X, y)

X_train, X_test, y_train, y_test = train_test_split(X_selected, y, test_size=0.2)
