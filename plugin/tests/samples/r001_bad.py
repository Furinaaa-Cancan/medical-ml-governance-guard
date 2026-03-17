# BAD: fit_transform before split
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import pandas as pd

df = pd.read_csv("data.csv")
X = df.drop(columns=["target"])
y = df["target"]

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)  # <-- leakage: fitting on full data

X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2)
