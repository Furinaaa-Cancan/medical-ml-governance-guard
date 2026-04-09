"""Red Team #1: Obvious — scaler fit on full data before split."""
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split

df = pd.read_csv("patient_data.csv")
X = df.drop(columns=["readmitted"])
y = df["readmitted"]

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)  # BUG: fit on full data

X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2)
