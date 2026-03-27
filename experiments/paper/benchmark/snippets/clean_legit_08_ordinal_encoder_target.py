from sklearn.preprocessing import OrdinalEncoder
from sklearn.model_selection import train_test_split
enc = OrdinalEncoder()
y_enc = enc.fit_transform(y.values.reshape(-1, 1)).ravel()
X_train, X_test, y_train, y_test = train_test_split(X, y_enc)
