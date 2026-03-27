from sklearn.preprocessing import PowerTransformer
from sklearn.model_selection import train_test_split
pt = PowerTransformer()
X_transformed = pt.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_transformed, y)
