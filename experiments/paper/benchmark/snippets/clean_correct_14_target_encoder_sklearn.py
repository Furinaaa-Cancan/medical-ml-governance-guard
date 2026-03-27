from sklearn.preprocessing import TargetEncoder
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
te = TargetEncoder()
X_train_e = te.fit_transform(X_train, y_train)
X_test_e = te.transform(X_test)
