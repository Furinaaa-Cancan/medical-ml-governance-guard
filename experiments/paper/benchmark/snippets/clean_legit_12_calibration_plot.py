from sklearn.calibration import calibration_curve
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
prob_true, prob_pred = calibration_curve(y_test, y_scores, n_bins=10)
