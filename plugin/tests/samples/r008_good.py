# GOOD: temporal split without shuffle
from sklearn.model_selection import train_test_split
import pandas as pd

df = pd.read_csv("events.csv")
event_time = df["event_time"]
df_sorted = df.sort_values("event_time")
X = df_sorted.drop(columns=["event_time", "target"])
y = df_sorted["target"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
