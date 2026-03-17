# GOOD: threshold selection on validation data (not test)
from sklearn.metrics import roc_curve
from sklearn.model_selection import train_test_split

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

# threshold selection on validation — correct practice
fpr, tpr, thresholds = roc_curve(y_valid, y_pred_valid)
best_threshold = thresholds[tpr - fpr > 0.5][0]
