"""Red Team #4: Patient-level split missing — same patient can be in train and test."""
import pandas as pd
from sklearn.model_selection import train_test_split

df = pd.read_csv("ehr_visits.csv")
# patient_id exists but not used for grouping
X = df.drop(columns=["patient_id", "mortality"])
y = df["mortality"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)  # BUG: no groups=patient_id, same patient may appear in both splits
