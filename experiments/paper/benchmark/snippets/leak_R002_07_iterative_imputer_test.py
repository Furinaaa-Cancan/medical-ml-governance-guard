from sklearn.experimental import enable_iterative_imputer
from sklearn.impute import IterativeImputer
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
imp = IterativeImputer()
X_train = imp.fit_transform(X_train)
X_test = imp.fit_transform(X_test)
