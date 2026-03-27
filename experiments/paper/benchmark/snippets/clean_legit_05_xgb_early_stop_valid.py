import xgboost as xgb
from sklearn.model_selection import train_test_split
X_train, X_valid, y_train, y_valid = train_test_split(X, y)
model = xgb.XGBClassifier(early_stopping_rounds=10)
model.fit(X_train, y_train, eval_set=[(X_valid, y_valid)])
