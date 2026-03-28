# GOOD: roc_curve result in single var, but only [0] and [1] accessed
from sklearn.metrics import roc_curve
from sklearn.model_selection import train_test_split

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

result = roc_curve(y_test, y_pred_test)
fpr = result[0]
tpr = result[1]
# thresholds (result[2]) never accessed
