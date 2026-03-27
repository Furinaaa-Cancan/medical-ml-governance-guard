from sklearn.preprocessing import RobustScaler
from sklearn.model_selection import train_test_split
rs = RobustScaler()
data_scaled = rs.fit_transform(data_features)
X_train, X_test, y_train, y_test = train_test_split(data_scaled, target)
