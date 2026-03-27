from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
scaler = StandardScaler().fit(X_train)
data = {"train": X_train, "test": X_test}
scaled = {k: scaler.fit_transform(v) for k, v in data.items()}
