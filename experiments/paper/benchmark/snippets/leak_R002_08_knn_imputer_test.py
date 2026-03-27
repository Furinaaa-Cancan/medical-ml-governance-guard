from sklearn.impute import KNNImputer
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
knn_imp = KNNImputer(n_neighbors=5)
X_test_clean = knn_imp.fit_transform(X_test)
