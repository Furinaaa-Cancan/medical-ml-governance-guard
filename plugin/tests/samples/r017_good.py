# GOOD: early stopping on validation data (not test)
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
X_trn, X_valid, y_trn, y_valid = train_test_split(X_train, y_train, test_size=0.25)
model = XGBClassifier(n_estimators=1000)
model.fit(X_trn, y_trn, eval_set=[(X_valid, y_valid)], early_stopping_rounds=10)
