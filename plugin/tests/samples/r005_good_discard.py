# GOOD: roc_curve on test but thresholds discarded — just evaluation
from sklearn.metrics import roc_curve
from sklearn.model_selection import train_test_split

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

fpr, tpr, _ = roc_curve(y_test, y_pred_test)
# only fpr/tpr used for plotting, thresholds discarded
