"""Red Team #5: Feature selection on full data before split."""
import pandas as pd
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.model_selection import train_test_split

df = pd.read_csv("clinical.csv")
X = df.drop(columns=["outcome"])
y = df["outcome"]

selector = SelectKBest(f_classif, k=20)
X_selected = selector.fit_transform(X, y)  # BUG: feature selection on full data

X_train, X_test, y_train, y_test = train_test_split(X_selected, y, test_size=0.2)
