from sklearn.preprocessing import Normalizer
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
norm = Normalizer()
X_test_norm = norm.fit_transform(X_test)
