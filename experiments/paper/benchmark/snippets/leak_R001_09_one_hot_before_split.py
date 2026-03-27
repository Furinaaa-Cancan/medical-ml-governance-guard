from sklearn.preprocessing import OneHotEncoder
from sklearn.model_selection import train_test_split
ohe = OneHotEncoder(sparse_output=False, handle_unknown='ignore')
X_encoded = ohe.fit_transform(X_cat)
X_train, X_test, y_train, y_test = train_test_split(X_encoded, y)
