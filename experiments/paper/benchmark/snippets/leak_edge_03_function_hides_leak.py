from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
def preprocess(data):
    scaler = StandardScaler()
    return scaler.fit_transform(data)
X_processed = preprocess(X)
X_train, X_test, y_train, y_test = train_test_split(X_processed, y)
