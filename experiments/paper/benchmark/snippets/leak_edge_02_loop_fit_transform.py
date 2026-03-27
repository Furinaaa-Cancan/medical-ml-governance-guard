from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
scaler = StandardScaler()
for split_name, split_data in [("train", X_train), ("test", X_test)]:
    scaled = scaler.fit_transform(split_data)
