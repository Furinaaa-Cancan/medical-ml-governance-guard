from sklearn.metrics import roc_curve
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
fpr, tpr, thresholds = roc_curve(y_test, model.predict_proba(X_test)[:, 1])
config['threshold'] = thresholds[np.argmax(tpr - fpr)]
