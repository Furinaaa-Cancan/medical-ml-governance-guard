# BAD: threshold selection on test data
from sklearn.metrics import roc_curve
from sklearn.model_selection import train_test_split
import pandas as pd

df = pd.read_csv("data.csv")
X = df.drop(columns=["target"])
y = df["target"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

# ... model training ...
fpr, tpr, thresholds = roc_curve(y_test, y_pred_test)
best_threshold = thresholds[tpr - fpr > 0.5][0]
