from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
imp = SimpleImputer(strategy='median')
X_train_clean = imp.fit_transform(X_train)
X_test_clean = imp.transform(X_test)
