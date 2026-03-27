import xgboost as xgb
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y)
model = xgb.XGBClassifier(early_stopping_rounds=10)
model.fit(X_train, y_train, eval_set=[(X_test, y_test)])
