from imblearn.over_sampling import SMOTE
from sklearn.model_selection import train_test_split
X_resampled, y_resampled = SMOTE().fit_resample(X, y)
X_train, X_test, y_train, y_test = train_test_split(X_resampled, y_resampled)
