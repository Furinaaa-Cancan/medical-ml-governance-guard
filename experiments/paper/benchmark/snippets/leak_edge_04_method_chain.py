from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X_scaled = StandardScaler().fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_scaled, y)
