from sklearn.metrics import precision_recall_curve
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
prec, rec, thresholds = precision_recall_curve(y_test, y_scores)
best_f1_idx = (2 * prec * rec / (prec + rec + 1e-8)).argmax()
best_thresh = thresholds[best_f1_idx]
