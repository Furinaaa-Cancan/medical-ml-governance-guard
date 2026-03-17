# BAD: early stopping on test data
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
model = XGBClassifier(n_estimators=1000)
model.fit(X_train, y_train, eval_set=[(X_test, y_test)], early_stopping_rounds=10)
