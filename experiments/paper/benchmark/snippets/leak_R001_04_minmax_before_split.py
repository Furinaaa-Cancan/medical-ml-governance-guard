from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
scaler = MinMaxScaler()
X_norm = scaler.fit_transform(features)
train_X, test_X, train_y, test_y = train_test_split(X_norm, labels, test_size=0.3)
