from sklearn.feature_selection import VarianceThreshold
from sklearn.model_selection import train_test_split
vt = VarianceThreshold(threshold=0.01)
X_vt = vt.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_vt, y)
