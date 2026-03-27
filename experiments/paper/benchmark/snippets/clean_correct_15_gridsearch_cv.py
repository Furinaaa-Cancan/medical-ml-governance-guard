from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
X_train, X_test, y_train, y_test = train_test_split(X, y)
pipe = Pipeline([('scaler', StandardScaler()), ('svc', SVC())])
gs = GridSearchCV(pipe, {'svc__C': [0.1, 1, 10]}, cv=5)
gs.fit(X_train, y_train)
