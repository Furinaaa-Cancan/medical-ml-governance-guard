from sklearn.preprocessing import QuantileTransformer
from sklearn.model_selection import train_test_split
qt = QuantileTransformer(output_distribution='normal')
X_qt = qt.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_qt, y)
