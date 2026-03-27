from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
imp = SimpleImputer(strategy="mean")
X_clean = imp.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_clean, y)
