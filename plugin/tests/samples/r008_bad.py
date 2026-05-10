# BAD: shuffle split on temporal data (DatetimeIndex evidence)
from sklearn.model_selection import train_test_split
import pandas as pd

df = pd.read_csv("events.csv")
df.index = pd.to_datetime(df["event_time"])
event_time = df["event_time"]
X = df.drop(columns=["event_time", "target"])
y = df["target"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
