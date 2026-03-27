from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingClassifier
X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.3, random_state=42)
X_valid, X_test, y_valid, y_test = train_test_split(X_temp, y_temp, test_size=0.5, random_state=42)
scaler = StandardScaler().fit(X_train)
X_train, X_valid, X_test = [scaler.transform(d) for d in [X_train, X_valid, X_test]]
model = GradientBoostingClassifier()
model.fit(X_train, y_train)
