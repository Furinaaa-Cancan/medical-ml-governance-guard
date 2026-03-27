from sklearn.preprocessing import PolynomialFeatures
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
poly = PolynomialFeatures(degree=2)
X_test_poly = poly.fit_transform(X_test)
