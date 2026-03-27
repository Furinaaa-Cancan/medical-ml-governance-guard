from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
features = data
labels = data['outcome']
X_train, X_test, y_train, y_test = train_test_split(features, labels)
lr = LogisticRegression()
lr.fit(X_train, y_train)
