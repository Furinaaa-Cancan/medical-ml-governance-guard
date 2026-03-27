from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
imputer = SimpleImputer()
imp = imputer.fit(X_train)
X_train_clean = imp.transform(X_train)
imp = imputer.fit(X_test)
X_test_clean = imp.transform(X_test)
