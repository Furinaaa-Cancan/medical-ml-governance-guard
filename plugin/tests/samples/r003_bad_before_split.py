# BAD: SMOTE on full data before split
from imblearn.over_sampling import SMOTE
from sklearn.model_selection import train_test_split

X_res, y_res = SMOTE().fit_resample(X, y)  # <-- leakage: before split
X_train, X_test, y_train, y_test = train_test_split(X_res, y_res)
