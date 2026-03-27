from sklearn.preprocessing import RobustScaler
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
rs = RobustScaler()
X_train_r = rs.fit_transform(X_train)
X_test_r = rs.transform(X_test)
