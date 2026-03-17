# GOOD: imputation after split, using training stats only
import pandas as pd
from sklearn.model_selection import train_test_split

df = pd.read_csv("data.csv")
X = df.drop(columns=["target"])
y = df["target"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

# Compute fill values from training data only
train_mean = X_train.mean()
X_train = X_train.fillna(train_mean)
X_test = X_test.fillna(train_mean)
