from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
rf = RandomForestClassifier()
rf.fit(X_train, y_train)
importances = rf.feature_importances_
