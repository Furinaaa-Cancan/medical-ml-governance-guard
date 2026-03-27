from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
sc = StandardScaler()
sc.fit(X_test)
X_test_scaled = sc.transform(X_test)
