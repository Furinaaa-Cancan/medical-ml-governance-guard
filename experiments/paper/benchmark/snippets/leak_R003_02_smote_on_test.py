from imblearn.over_sampling import SMOTE
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
sm = SMOTE()
X_test_res, y_test_res = sm.fit_resample(X_test, y_test)
